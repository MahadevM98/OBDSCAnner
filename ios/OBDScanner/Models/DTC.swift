import Foundation

/// Diagnostic Trouble Code decoding + description table (ported from dtc.py).
enum DTC {
    private static let letters: [UInt8: String] = [0: "P", 1: "C", 2: "B", 3: "U"]
    private static let category: [String: String] = [
        "P": "Powertrain (engine/transmission)",
        "C": "Chassis (ABS/brakes/steering)",
        "B": "Body (airbag/AC/lighting)",
        "U": "Network / communication bus",
    ]

    /// Decode a 2-byte DTC. Returns nil for the 0x0000 padding entry.
    static func decode(_ a: UInt8, _ b: UInt8) -> String? {
        if a == 0 && b == 0 { return nil }
        let letter = letters[(a & 0xC0) >> 6] ?? "P"
        let d1 = (a & 0x30) >> 4
        let d2 = a & 0x0F
        let d3 = (b & 0xF0) >> 4
        let d4 = b & 0x0F
        return "\(letter)\(d1)" + String(format: "%X%X%X", Int(d2), Int(d3), Int(d4))
    }

    static func describe(_ code: String) -> String {
        if let d = descriptions[code] { return d }
        let letter = code.first.map(String.init) ?? "?"
        let cat = category[letter] ?? "Unknown system"
        let kind = (code.count > 1 && Array(code)[1] == "1")
            ? "manufacturer-specific" : "generic"
        return "\(cat) - \(kind) code (see Honda service manual)"
    }

    static let descriptions: [String: String] = [
        "P0300": "Random/multiple cylinder misfire detected",
        "P0301": "Cylinder 1 misfire detected",
        "P0302": "Cylinder 2 misfire detected",
        "P0303": "Cylinder 3 misfire detected",
        "P0304": "Cylinder 4 misfire detected",
        "P0101": "MAF sensor circuit range/performance",
        "P0102": "MAF sensor circuit low input",
        "P0103": "MAF sensor circuit high input",
        "P0106": "MAP/Barometric pressure circuit range/performance",
        "P0107": "MAP sensor circuit low input",
        "P0108": "MAP sensor circuit high input",
        "P0111": "Intake air temp sensor range/performance",
        "P0112": "Intake air temp sensor low input",
        "P0113": "Intake air temp sensor high input",
        "P0116": "Engine coolant temp sensor range/performance",
        "P0117": "Engine coolant temp sensor low input",
        "P0118": "Engine coolant temp sensor high input",
        "P0122": "Throttle position sensor A low input",
        "P0123": "Throttle position sensor A high input",
        "P0128": "Coolant thermostat (temp below regulating temp)",
        "P0133": "O2 sensor B1S1 slow response",
        "P0134": "O2 sensor B1S1 no activity detected",
        "P0135": "O2 sensor B1S1 heater circuit malfunction",
        "P0137": "O2 sensor B1S2 low voltage",
        "P0138": "O2 sensor B1S2 high voltage",
        "P0141": "O2 sensor B1S2 heater circuit malfunction",
        "P0171": "System too lean (Bank 1)",
        "P0172": "System too rich (Bank 1)",
        "P0401": "EGR insufficient flow detected",
        "P0420": "Catalyst system efficiency below threshold (Bank 1)",
        "P0430": "Catalyst system efficiency below threshold (Bank 2)",
        "P0441": "EVAP system incorrect purge flow",
        "P0442": "EVAP system small leak detected",
        "P0446": "EVAP vent control circuit malfunction",
        "P0455": "EVAP system large leak detected (loose gas cap)",
        "P0456": "EVAP system very small leak detected",
        "P0505": "Idle air control system malfunction",
        "P0506": "Idle speed lower than expected",
        "P0507": "Idle speed higher than expected",
        "P0335": "Crankshaft position sensor A circuit",
        "P0340": "Camshaft position sensor circuit",
        "P0327": "Knock sensor 1 low input (Bank 1)",
        "P0328": "Knock sensor 1 high input (Bank 1)",
        "P0011": "Intake camshaft timing over-advanced (Bank 1)",
        "P0014": "Exhaust camshaft timing over-advanced (Bank 1)",
        "P0017": "Crank/cam position correlation (Bank 1 Sensor B)",
        "P0521": "Engine oil pressure sensor range/performance",
        "P0700": "Transmission control system malfunction",
        "P0715": "Input/turbine speed sensor circuit",
        "P0720": "Output speed sensor circuit",
        "P0730": "Incorrect gear ratio",
        "P0740": "Torque converter clutch circuit malfunction",
        "P0560": "System voltage malfunction",
        "P0562": "System voltage low",
        "P0563": "System voltage high",
        "U0073": "Control module communication bus A off",
        "U0100": "Lost communication with ECM/PCM A",
        "U0101": "Lost communication with TCM",
        "U0121": "Lost communication with ABS control module",
        "P1009": "VTC advance malfunction",
        "P1077": "IMRC / intake manifold runner control (low rpm)",
        "P1078": "IMRC / intake manifold runner control (high rpm)",
        "P1128": "MAP lower than expected (Honda)",
        "P1129": "MAP higher than expected (Honda)",
        "P1157": "Air-fuel ratio sensor circuit (Honda)",
        "P1259": "VTEC system malfunction (Honda)",
        "P1361": "TDC sensor intermittent interruption (Honda)",
        "P1456": "EVAP emission control - fuel tank system leak (Honda)",
        "P1457": "EVAP emission control - canister system leak (Honda)",
        "P1486": "Thermostat range/performance (Honda)",
        "P1659": "VTEC oil pressure switch (Honda)",
    ]
}
