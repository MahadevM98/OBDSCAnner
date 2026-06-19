import Foundation

/// Whole-vehicle extract (ported from extract.py): one pass across every mode
/// the adapter can reach, plus a shareable text rendering.
struct VehicleReport {
    var generated = Date()
    var session: [(String, String)] = []
    var vehicle: [(String, String)] = []
    var readiness: [(String, String)] = []
    var liveData: [(pid: UInt8, name: String, value: String, unit: String)] = []
    var stored: [DTCEntry] = []
    var pending: [DTCEntry] = []
    var permanent: [DTCEntry] = []
    var freeze = FreezeFrame()
    var mode06: [Mode06.TestResult] = []
}

enum Extract {

    /// Run the full sequence. `progress` is called before each section so the
    /// UI can show what's happening. Each section is wrapped so one unsupported
    /// service never aborts the rest.
    @MainActor
    static func full(_ elm: ELM327,
                     progress: (String) -> Void) async -> VehicleReport {
        var r = VehicleReport()

        progress("Session info")
        r.session = [
            ("Adapter", elm.adapterID),
            ("Protocol", elm.protocolName),
            ("Battery voltage", (try? await elm.command("ATRV")) ?? ""),
        ]

        progress("Vehicle info (Mode 09)")
        let vin = (try? await elm.readVIN()) ?? ""
        r.vehicle = [("VIN", vin.isEmpty ? "(not reported)" : vin)]
        r.vehicle += (try? await elm.readVehicleInfo()) ?? []

        progress("Readiness monitors")
        r.readiness = (try? await elm.readMonitors()) ?? []

        progress("Live sensors (Mode 01)")
        if let supported = try? await elm.supportedPIDs() {
            for pid in supported.sorted() where PIDs.table[pid] != nil {
                if let triple = try? await elm.queryPID(pid) {
                    r.liveData.append((pid, triple.0, triple.1.display, triple.2))
                }
            }
        }

        progress("Trouble codes")
        r.stored = (try? await elm.readStoredDTCs()) ?? []
        r.pending = (try? await elm.readPendingDTCs()) ?? []
        r.permanent = (try? await elm.readPermanentDTCs()) ?? []

        progress("Freeze frame (Mode 02)")
        r.freeze = (try? await elm.readFreezeFrame()) ?? FreezeFrame()

        progress("On-board monitors (Mode 06)")
        r.mode06 = (try? await elm.readMode06()) ?? []

        return r
    }

    static func toText(_ r: VehicleReport) -> String {
        var L: [String] = []
        let df = ISO8601DateFormatter()
        L.append(String(repeating: "=", count: 56))
        L.append("  OBD-II FULL VEHICLE EXTRACT")
        L.append("  Generated: \(df.string(from: r.generated))")
        L.append(String(repeating: "=", count: 56))

        func section(_ title: String, _ rows: [(String, String)]) {
            L.append(""); L.append("--- \(title) ---")
            for (k, v) in rows { L.append("  \(k.padding(toLength: 32, withPad: " ", startingAt: 0)) \(v)") }
        }
        section("SESSION", r.session)
        section("VEHICLE", r.vehicle)
        section("READINESS MONITORS", r.readiness)

        L.append(""); L.append("--- LIVE SENSORS (Mode 01) ---")
        for row in r.liveData {
            L.append("  \(row.name.padding(toLength: 32, withPad: " ", startingAt: 0)) \(row.value) \(row.unit)")
        }

        L.append(""); L.append("--- TROUBLE CODES ---")
        for (kind, codes) in [("Stored", r.stored), ("Pending", r.pending), ("Permanent", r.permanent)] {
            L.append("  \(kind): " + (codes.isEmpty ? "none" : ""))
            for c in codes { L.append("    \(c.code)  \(c.desc)") }
        }

        L.append(""); L.append("--- FREEZE FRAME (Mode 02) ---")
        L.append("  Triggered by DTC: \(r.freeze.dtc.isEmpty ? "(none)" : r.freeze.dtc)")
        for v in r.freeze.values {
            L.append("  \(v.name.padding(toLength: 32, withPad: " ", startingAt: 0)) \(v.value) \(v.unit)")
        }

        L.append(""); L.append("--- ON-BOARD MONITORS (Mode 06) ---")
        if r.mode06.isEmpty { L.append("  none reported") }
        for t in r.mode06 {
            L.append("  [\(t.verdict)] \(t.name.padding(toLength: 28, withPad: " ", startingAt: 0)) "
                + "val=\(t.value) min=\(t.lo) max=\(t.hi)")
        }
        L.append("")
        return L.joined(separator: "\n")
    }
}
