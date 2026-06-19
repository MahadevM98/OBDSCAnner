import Foundation

/// Mode 06 on-board monitor test results (ported from mode06.py).
/// Reports raw value/min/max + a scale-invariant PASS/FAIL verdict rather than
/// guessing the ECU-defined unit scaling.
enum Mode06 {
    static let midNames: [UInt8: String] = [
        0x01: "O2 Sensor Monitor B1S1",
        0x02: "O2 Sensor Monitor B1S2",
        0x03: "O2 Sensor Monitor B1S3",
        0x04: "O2 Sensor Monitor B1S4",
        0x05: "O2 Sensor Monitor B2S1",
        0x06: "O2 Sensor Monitor B2S2",
        0x21: "Catalyst Monitor Bank 1",
        0x22: "Catalyst Monitor Bank 2",
        0x31: "EGR Monitor Bank 1",
        0x32: "EGR Monitor Bank 2",
        0x39: "EVAP Monitor (Cap Off / large leak)",
        0x3B: "EVAP Monitor (0.040\")",
        0x3C: "EVAP Monitor (0.020\")",
        0x3D: "Purge Flow Monitor",
        0x41: "O2 Heater Monitor B1S1",
        0x42: "O2 Heater Monitor B1S2",
        0x45: "O2 Heater Monitor B2S1",
    ]

    static func midName(_ mid: UInt8) -> String {
        midNames[mid] ?? String(format: "Monitor 0x%02X", Int(mid))
    }

    struct TestResult: Identifiable {
        let id = UUID()
        let mid: UInt8
        let tid: UInt8
        let uas: UInt8
        let value: Int
        let lo: Int
        let hi: Int

        var passed: Bool { lo <= value && value <= hi }
        var verdict: String { passed ? "PASS" : "FAIL" }
        var name: String { Mode06.midName(mid) }
    }

    /// Parse the flattened payload following the 0x46 mode byte (9-byte stride).
    static func parse(_ data: [UInt8]) -> [TestResult] {
        var out: [TestResult] = []
        var i = 0
        while i + 9 <= data.count {
            let mid = data[i], tid = data[i+1], uas = data[i+2]
            let value = Int(data[i+3]) << 8 | Int(data[i+4])
            let lo = Int(data[i+5]) << 8 | Int(data[i+6])
            let hi = Int(data[i+7]) << 8 | Int(data[i+8])
            if mid != 0x00 {
                out.append(TestResult(mid: mid, tid: tid, uas: uas,
                                      value: value, lo: lo, hi: hi))
            }
            i += 9
        }
        return out
    }
}
