import Foundation

/// A decoded PID value: numeric for sensors, text for status PIDs.
enum OBDValue {
    case number(Double)
    case text(String)

    var display: String {
        switch self {
        case .number(let d):
            // Trim trailing .0 for whole numbers.
            return d == d.rounded() ? String(Int(d)) : String(format: "%.2f", d)
        case .text(let s): return s
        }
    }
    var number: Double? {
        if case .number(let d) = self { return d }
        return nil
    }
}

struct PIDDef {
    let name: String
    let unit: String
    let decode: ([UInt8]) -> OBDValue
}

enum PIDs {

    // safe byte access (Python _u)
    private static func u(_ b: [UInt8], _ i: Int) -> Int {
        i < b.count ? Int(b[i]) : 0
    }
    private static func n(_ d: Double) -> OBDValue { .number(d) }
    private static func round1(_ d: Double) -> Double { (d * 10).rounded() / 10 }
    private static func round2(_ d: Double) -> Double { (d * 100).rounded() / 100 }
    private static func round3(_ d: Double) -> Double { (d * 1000).rounded() / 1000 }
    private static func round4(_ d: Double) -> Double { (d * 10000).rounded() / 10000 }

    private static func percent(_ b: [UInt8]) -> OBDValue { n(round1(Double(u(b,0)) * 100 / 255)) }
    private static func temp(_ b: [UInt8]) -> OBDValue { n(Double(u(b,0) - 40)) }
    private static func fueltrim(_ b: [UInt8]) -> OBDValue { n(round1(Double(u(b,0) - 128) * 100 / 128)) }
    private static func map(_ b: [UInt8]) -> OBDValue { n(Double(u(b,0))) }
    private static func rpm(_ b: [UInt8]) -> OBDValue { n((Double(u(b,0)) * 256 + Double(u(b,1))) / 4) }
    private static func timing(_ b: [UInt8]) -> OBDValue { n(round1(Double(u(b,0)) / 2 - 64)) }
    private static func maf(_ b: [UInt8]) -> OBDValue { n(round2((Double(u(b,0)) * 256 + Double(u(b,1))) / 100)) }
    private static func o2v(_ b: [UInt8]) -> OBDValue { n(round3(Double(u(b,0)) / 200)) }
    private static func word(_ b: [UInt8]) -> OBDValue { n(Double(u(b,0) * 256 + u(b,1))) }
    private static func ctrlV(_ b: [UInt8]) -> OBDValue { n(round3((Double(u(b,0)) * 256 + Double(u(b,1))) / 1000)) }
    private static func wbLambda(_ b: [UInt8]) -> OBDValue { n(round4((Double(u(b,0)) * 256 + Double(u(b,1))) / 32768)) }
    private static func baro(_ b: [UInt8]) -> OBDValue { n(Double(u(b,0))) }

    private static let fuelSys: [Int: String] = [
        0x00: "off", 0x01: "open (warm-up)", 0x02: "closed loop",
        0x04: "open (load/decel)", 0x08: "open (fault)", 0x10: "closed (fault)",
    ]
    private static func fuelStatus(_ b: [UInt8]) -> OBDValue {
        let a = u(b, 0)
        return .text(fuelSys[a] ?? String(format: "0x%02X", a))
    }

    static let table: [UInt8: PIDDef] = [
        0x03: PIDDef(name: "Fuel system status", unit: "", decode: fuelStatus),
        0x04: PIDDef(name: "Calculated engine load", unit: "%", decode: percent),
        0x05: PIDDef(name: "Engine coolant temp", unit: "°C", decode: temp),
        0x06: PIDDef(name: "Short term fuel trim B1", unit: "%", decode: fueltrim),
        0x07: PIDDef(name: "Long term fuel trim B1", unit: "%", decode: fueltrim),
        0x08: PIDDef(name: "Short term fuel trim B2", unit: "%", decode: fueltrim),
        0x09: PIDDef(name: "Long term fuel trim B2", unit: "%", decode: fueltrim),
        0x0A: PIDDef(name: "Fuel pressure", unit: "kPa", decode: { n(Double(u($0,0) * 3)) }),
        0x0B: PIDDef(name: "Intake manifold pressure", unit: "kPa", decode: map),
        0x0C: PIDDef(name: "Engine RPM", unit: "rpm", decode: rpm),
        0x0D: PIDDef(name: "Vehicle speed", unit: "km/h", decode: { n(Double(u($0,0))) }),
        0x0E: PIDDef(name: "Timing advance", unit: "°", decode: timing),
        0x0F: PIDDef(name: "Intake air temp", unit: "°C", decode: temp),
        0x10: PIDDef(name: "MAF air flow", unit: "g/s", decode: maf),
        0x11: PIDDef(name: "Throttle position", unit: "%", decode: percent),
        0x14: PIDDef(name: "O2 S1 voltage", unit: "V", decode: o2v),
        0x15: PIDDef(name: "O2 S2 voltage", unit: "V", decode: o2v),
        0x1F: PIDDef(name: "Run time since start", unit: "s", decode: word),
        0x21: PIDDef(name: "Distance with MIL on", unit: "km", decode: word),
        0x24: PIDDef(name: "O2 S1 wide-range λ", unit: "λ", decode: wbLambda),
        0x25: PIDDef(name: "O2 S2 wide-range λ", unit: "λ", decode: wbLambda),
        0x2C: PIDDef(name: "Commanded EGR", unit: "%", decode: { n(round1(Double(u($0,0)) * 100 / 255)) }),
        0x2E: PIDDef(name: "Commanded evap purge", unit: "%", decode: percent),
        0x2F: PIDDef(name: "Fuel tank level", unit: "%", decode: percent),
        0x31: PIDDef(name: "Distance since codes cleared", unit: "km", decode: word),
        0x33: PIDDef(name: "Barometric pressure", unit: "kPa", decode: baro),
        0x42: PIDDef(name: "Control module voltage", unit: "V", decode: ctrlV),
        0x43: PIDDef(name: "Absolute load value", unit: "%", decode: { n(round1((Double(u($0,0)) * 256 + Double(u($0,1))) * 100 / 255)) }),
        0x45: PIDDef(name: "Relative throttle position", unit: "%", decode: percent),
        0x46: PIDDef(name: "Ambient air temp", unit: "°C", decode: temp),
        0x47: PIDDef(name: "Absolute throttle pos B", unit: "%", decode: percent),
        0x49: PIDDef(name: "Accelerator pedal pos D", unit: "%", decode: percent),
        0x4A: PIDDef(name: "Accelerator pedal pos E", unit: "%", decode: percent),
        0x4C: PIDDef(name: "Commanded throttle actuator", unit: "%", decode: percent),
        0x52: PIDDef(name: "Ethanol fuel %", unit: "%", decode: percent),
        0x5A: PIDDef(name: "Relative accelerator pedal", unit: "%", decode: percent),
        0x5B: PIDDef(name: "Hybrid battery remaining", unit: "%", decode: percent),
        0x5C: PIDDef(name: "Engine oil temp", unit: "°C", decode: temp),
    ]

    /// Returns (name, value, unit) or nil for an unknown PID.
    static func decode(_ pid: UInt8, _ bytes: [UInt8]) -> (String, OBDValue, String)? {
        guard let def = table[pid] else { return nil }
        return (def.name, def.decode(bytes), def.unit)
    }

    /// Default dashboard set (only those the ECU reports are shown).
    static let dashboard: [UInt8] = [
        0x0C, 0x0D, 0x05, 0x0F, 0x04, 0x11, 0x10,
        0x06, 0x07, 0x0E, 0x0B, 0x33, 0x2F, 0x42,
    ]
}
