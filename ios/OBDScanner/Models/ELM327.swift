import Foundation

/// OBD-II driver over the BLE transport. Async port of elm327.py — every
/// method awaits the adapter's reply. Parsing mirrors the Python driver.
struct DTCEntry: Identifiable {
    let id = UUID()
    let code: String
    let desc: String
}

struct ServiceResult {
    let raw: String
    let ok: Bool
    let detail: String
}

struct FreezeFrame {
    var dtc: String = ""
    var values: [(pid: UInt8, name: String, value: String, unit: String)] = []
}

@MainActor
final class ELM327 {
    let ble: BLEManager
    var adapterID = ""
    var protocolName = ""

    init(_ ble: BLEManager) { self.ble = ble }

    // MARK: low-level

    /// Send a command and strip the echoed command line.
    func command(_ cmd: String) async throws -> String {
        let raw = try await ble.send(cmd)
        let wanted = cmd.uppercased().replacingOccurrences(of: " ", with: "")
        let lines = raw.replacingOccurrences(of: "\r", with: "\n")
            .split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .filter { $0.uppercased().replacingOccurrences(of: " ", with: "") != wanted }
        return lines.joined(separator: "\n")
    }

    static func hexBytes(_ line: String) -> [UInt8] {
        let s = line.replacingOccurrences(of: " ", with: "")
        guard s.count >= 2 else { return [] }
        var out: [UInt8] = []
        let chars = Array(s)
        var i = 0
        while i + 1 < chars.count {
            if let v = UInt8(String(chars[i...i+1]), radix: 16) { out.append(v) }
            else { return [] }
            i += 2
        }
        return out
    }

    static func isError(_ resp: String) -> Bool {
        let up = resp.uppercased()
        if resp.isEmpty { return true }
        let bad = ["NO DATA", "ERROR", "UNABLE TO CONNECT", "BUS INIT",
                   "CAN ERROR", "STOPPED", "?", "SEARCHING"]
        return bad.contains { up.contains($0) }
    }

    // MARK: session

    func initialize() async throws -> [String: String] {
        var info: [String: String] = [:]
        _ = try? await command("ATZ")
        try? await Task.sleep(nanoseconds: 400_000_000)
        for c in ["ATE0", "ATL0", "ATS0", "ATH0", "ATSP0"] { _ = try? await command(c) }
        adapterID = (try? await command("ATI")) ?? ""
        info["adapter"] = adapterID
        _ = try? await command("0100")              // wake the OBD link
        let dpn = (try? await command("ATDPN")) ?? ""
        let dp = (try? await command("ATDP")) ?? ""
        protocolName = "\(dp) (\(dpn))".trimmingCharacters(in: .whitespaces)
        info["protocol"] = protocolName
        info["voltage"] = (try? await command("ATRV")) ?? ""
        return info
    }

    // MARK: Mode 01

    func queryPID(_ pid: UInt8) async throws -> (String, OBDValue, String)? {
        let resp = try await command(String(format: "01%02X", Int(pid)))
        if Self.isError(resp) { return nil }
        for line in resp.split(separator: "\n") {
            let b = Self.hexBytes(String(line))
            if b.count >= 2 && b[0] == 0x41 && b[1] == pid {
                return PIDs.decode(pid, Array(b[2...]))
            }
        }
        return nil
    }

    func supportedPIDs() async throws -> Set<UInt8> {
        var found = Set<UInt8>()
        for base in [0x00, 0x20, 0x40, 0x60, 0x80] as [UInt8] {
            let resp = try await command(String(format: "01%02X", Int(base)))
            if Self.isError(resp) { break }
            var bitmap: [UInt8]? = nil
            for line in resp.split(separator: "\n") {
                let b = Self.hexBytes(String(line))
                if b.count >= 6 && b[0] == 0x41 && b[1] == base {
                    bitmap = Array(b[2..<6]); break
                }
            }
            guard let bm = bitmap else { break }
            let value = UInt32(bm[0]) << 24 | UInt32(bm[1]) << 16 | UInt32(bm[2]) << 8 | UInt32(bm[3])
            for i in 0..<32 where (value & (UInt32(1) << UInt32(31 - i))) != 0 {
                found.insert(base + UInt8(i) + 1)
            }
            if (value & 0x1) == 0 { break }
        }
        for m in [0x20, 0x40, 0x60, 0x80] as [UInt8] { found.remove(m) }
        return found
    }

    // MARK: Mode 03 / 07 / 0A

    private func readDTCs(_ mode: String, _ prefix: UInt8) async throws -> [DTCEntry] {
        let resp = try await command(mode)
        if Self.isError(resp) { return [] }
        var tokens: [String] = []
        for line in resp.split(separator: "\n") {
            for tok in line.split(separator: " ") {
                if tok.hasSuffix(":") { continue }      // frame counter
                tokens.append(String(tok))
            }
        }
        var data = Self.hexBytes(tokens.joined())
        if let idx = data.firstIndex(of: prefix) { data = Array(data[(idx + 1)...]) }
        if data.count % 2 == 1 { data = Array(data.dropFirst()) }   // CAN count byte
        var out: [DTCEntry] = []
        var seen = Set<String>()
        var i = 0
        while i + 1 < data.count {
            if let code = DTC.decode(data[i], data[i+1]), !seen.contains(code) {
                seen.insert(code)
                out.append(DTCEntry(code: code, desc: DTC.describe(code)))
            }
            i += 2
        }
        return out
    }

    func readStoredDTCs() async throws -> [DTCEntry] { try await readDTCs("03", 0x43) }
    func readPendingDTCs() async throws -> [DTCEntry] { try await readDTCs("07", 0x47) }
    func readPermanentDTCs() async throws -> [DTCEntry] { try await readDTCs("0A", 0x4A) }

    func clearDTCs() async throws -> Bool {
        let resp = try await command("04")
        if resp.uppercased().replacingOccurrences(of: " ", with: "").contains("44") {
            return true
        }
        return !Self.isError(resp)
    }

    // MARK: Mode 09

    func readVIN() async throws -> String {
        let resp = try await command("0902")
        if Self.isError(resp) { return "" }
        var payload: [UInt8] = []
        for line in resp.split(separator: "\n") {
            let b = Self.hexBytes(String(line))
            if b.isEmpty { continue }
            if let idx = b.firstIndex(of: 0x49), idx + 3 <= b.count {
                payload.append(contentsOf: b[(idx + 3)...])
            } else {
                payload.append(contentsOf: b)
            }
        }
        let chars = payload.filter { $0 >= 32 && $0 <= 126 }.map { Character(UnicodeScalar($0)) }
        let vin = String(chars).trimmingCharacters(in: .whitespaces)
        return vin.count >= 17 ? String(vin.suffix(17)) : vin
    }

    private func mode09Payload(_ pid: UInt8) async throws -> [UInt8] {
        let resp = try await command(String(format: "09%02X", Int(pid)))
        if Self.isError(resp) { return [] }
        var payload: [UInt8] = []
        for line in resp.split(separator: "\n") {
            let b = Self.hexBytes(String(line))
            if b.isEmpty { continue }
            if let idx = b.firstIndex(of: 0x49), idx + 3 <= b.count {
                payload.append(contentsOf: b[(idx + 3)...])
            } else {
                payload.append(contentsOf: b)
            }
        }
        return payload
    }

    func readVehicleInfo() async throws -> [(String, String)] {
        var info: [(String, String)] = []
        func ascii(_ p: [UInt8]) -> String {
            String(p.filter { $0 >= 32 && $0 <= 126 }.map { Character(UnicodeScalar($0)) })
                .trimmingCharacters(in: .whitespaces)
        }
        let cal = ascii(try await mode09Payload(0x04))
        if !cal.isEmpty { info.append(("Calibration ID", cal)) }
        let cvn = try await mode09Payload(0x06)
        if !cvn.isEmpty {
            info.append(("Calibration Verification (CVN)",
                         cvn.map { String(format: "%02X", $0) }.joined(separator: " ")))
        }
        let ecu = ascii(try await mode09Payload(0x0A))
        if !ecu.isEmpty { info.append(("ECU name", ecu)) }
        return info
    }

    // MARK: Mode 02 freeze frame

    func readFreezeFrame(_ pids: [UInt8] = PIDs.dashboard) async throws -> FreezeFrame {
        var ff = FreezeFrame()
        let resp = try await command("020200")
        for line in resp.split(separator: "\n") {
            let b = Self.hexBytes(String(line))
            if b.count >= 5 && b[0] == 0x42 && b[1] == 0x02 {
                if let code = DTC.decode(b[3], b[4]) { ff.dtc = code }
                break
            }
        }
        for pid in pids where PIDs.table[pid] != nil {
            let r = try await command(String(format: "02%02X00", Int(pid)))
            if Self.isError(r) { continue }
            for line in r.split(separator: "\n") {
                let b = Self.hexBytes(String(line))
                if b.count >= 3 && b[0] == 0x42 && b[1] == pid {
                    if let (name, value, unit) = PIDs.decode(pid, Array(b[3...])) {
                        ff.values.append((pid, name, value.display, unit))
                    }
                    break
                }
            }
        }
        return ff
    }

    // MARK: Mode 06

    func supportedMIDs() async throws -> Set<UInt8> {
        var found = Set<UInt8>()
        for base in [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0] as [UInt8] {
            let resp = try await command(String(format: "06%02X", Int(base)))
            if Self.isError(resp) { break }
            var bitmap: [UInt8]? = nil
            for line in resp.split(separator: "\n") {
                let b = Self.hexBytes(String(line))
                if b.count >= 6 && b[0] == 0x46 && b[1] == base {
                    bitmap = Array(b[2..<6]); break
                }
            }
            guard let bm = bitmap else { break }
            let value = UInt32(bm[0]) << 24 | UInt32(bm[1]) << 16 | UInt32(bm[2]) << 8 | UInt32(bm[3])
            for i in 0..<32 where (value & (UInt32(1) << UInt32(31 - i))) != 0 {
                found.insert(base + UInt8(i) + 1)
            }
            if (value & 0x1) == 0 { break }
        }
        for m in [0x20, 0x40, 0x60, 0x80, 0xA0] as [UInt8] { found.remove(m) }
        return found
    }

    func readMode06() async throws -> [Mode06.TestResult] {
        var results: [Mode06.TestResult] = []
        for mid in try await supportedMIDs().sorted() {
            let resp = try await command(String(format: "06%02X", Int(mid)))
            if Self.isError(resp) { continue }
            var tokens: [String] = []
            for line in resp.split(separator: "\n") {
                for tok in line.split(separator: " ") where !tok.hasSuffix(":") {
                    tokens.append(String(tok))
                }
            }
            var data = Self.hexBytes(tokens.joined())
            if let idx = data.firstIndex(of: 0x46) { data = Array(data[(idx + 1)...]) }
            results.append(contentsOf: Mode06.parse(data))
        }
        return results
    }

    // MARK: readiness monitors (Mode 01 PID 01)

    func readMonitors() async throws -> [(String, String)] {
        let resp = try await command("0101")
        if Self.isError(resp) { return [] }
        var b: [UInt8] = []
        for line in resp.split(separator: "\n") {
            let bb = Self.hexBytes(String(line))
            if bb.count >= 6 && bb[0] == 0x41 && bb[1] == 0x01 { b = Array(bb[2..<6]); break }
        }
        guard b.count >= 4 else { return [] }
        let A = b[0], B = b[1], C = b[2], D = b[3]
        var out: [(String, String)] = [
            ("MIL (check engine lamp)", (A & 0x80) != 0 ? "ON" : "off"),
            ("Stored DTC count", String(A & 0x7F)),
        ]
        let cont: [(String, UInt8)] = [
            ("Misfire monitor", 0x01), ("Fuel system monitor", 0x02),
            ("Components monitor", 0x04),
        ]
        for (name, mask) in cont {
            out.append((name, (B & mask) != 0 ? ((B & (mask << 4)) != 0 ? "NOT ready" : "Ready") : "n/a"))
        }
        let nonCont: [(String, UInt8)] = [
            ("Catalyst", 0x01), ("Heated catalyst", 0x02), ("EVAP system", 0x04),
            ("Secondary air", 0x08), ("O2 sensor", 0x20),
            ("O2 sensor heater", 0x40), ("EGR system", 0x80),
        ]
        for (name, mask) in nonCont {
            out.append((name, (C & mask) != 0 ? ((D & mask) != 0 ? "NOT ready" : "Ready") : "n/a"))
        }
        return out
    }

    // MARK: service / actuator commands

    static let nrc: [UInt8: String] = [
        0x10: "general reject", 0x11: "service not supported",
        0x12: "sub-function not supported", 0x13: "wrong message length",
        0x22: "conditions not correct", 0x31: "request out of range",
        0x33: "security access denied", 0x35: "invalid key",
        0x78: "response pending", 0x7E: "service not supported in session",
        0x7F: "service not supported in active session",
    ]

    func runCommand(_ cmd: String, expect: UInt8?) async throws -> ServiceResult {
        let raw = try await command(cmd)
        if Self.isError(raw) {
            return ServiceResult(raw: raw, ok: false, detail: raw.isEmpty ? "no response" : raw)
        }
        let flat = Self.hexBytes(raw.replacingOccurrences(of: "\n", with: " ")
                                    .replacingOccurrences(of: " ", with: ""))
        if let i = flat.firstIndex(of: 0x7F) {
            let nrcByte = i + 2 < flat.count ? flat[i + 2] : nil
            let reason = nrcByte.flatMap { Self.nrc[$0] }
                ?? (nrcByte.map { String(format: "code 0x%02X", $0) } ?? "?")
            return ServiceResult(raw: raw, ok: false, detail: "ECU rejected request: \(reason)")
        }
        if let e = expect {
            let ok = flat.contains(e)
            return ServiceResult(raw: raw, ok: ok,
                                 detail: ok ? "Positive response." : "Unexpected response.")
        }
        return ServiceResult(raw: raw, ok: true, detail: "Command sent.")
    }
}
