"""
Diagnostic Trouble Code (DTC) decoding and a description database.

decode_dtc() turns two raw bytes into a code like "P0301".

The DTC_DESCRIPTIONS dict covers the generic SAE J2012 powertrain codes most
likely to appear on a Honda Accord 8th gen 2.4L (K24), plus a selection of
Honda manufacturer-specific (P1xxx) codes. Codes not in the table still
decode to a valid identifier and are labelled by category.
"""

from __future__ import annotations

# First two bits of the first byte select the system letter.
_LETTER = {0b00: "P", 0b01: "C", 0b10: "B", 0b11: "U"}
_CATEGORY = {
    "P": "Powertrain (engine/transmission)",
    "C": "Chassis (ABS/brakes/steering)",
    "B": "Body (airbag/AC/lighting)",
    "U": "Network / communication bus",
}


def decode_dtc(byte_a: int, byte_b: int) -> str | None:
    """Decode a 2-byte DTC. Returns None for the 0x0000 padding entry."""
    if byte_a == 0 and byte_b == 0:
        return None
    letter = _LETTER[(byte_a & 0xC0) >> 6]
    d1 = (byte_a & 0x30) >> 4
    d2 = byte_a & 0x0F
    d3 = (byte_b & 0xF0) >> 4
    d4 = byte_b & 0x0F
    return f"{letter}{d1}{d2:X}{d3:X}{d4:X}"


def describe(code: str) -> str:
    """Human description for a DTC; falls back to the system category."""
    if code in DTC_DESCRIPTIONS:
        return DTC_DESCRIPTIONS[code]
    letter = code[0] if code else "?"
    cat = _CATEGORY.get(letter, "Unknown system")
    kind = "manufacturer-specific" if len(code) > 1 and code[1] == "1" else "generic"
    return f"{cat} - {kind} code (see Honda service manual)"


DTC_DESCRIPTIONS = {
    # --- Misfire (very common on aging K24) ---
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0305": "Cylinder 5 misfire detected",
    "P0306": "Cylinder 6 misfire detected",
    # --- Fuel & air metering ---
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
    "P0139": "O2 sensor B1S2 slow response",
    "P0141": "O2 sensor B1S2 heater circuit malfunction",
    "P0171": "System too lean (Bank 1)",
    "P0172": "System too rich (Bank 1)",
    "P0174": "System too lean (Bank 2)",
    "P0175": "System too rich (Bank 2)",
    # --- Catalyst / emissions (P0420 is the classic Accord code) ---
    "P0401": "EGR insufficient flow detected",
    "P0420": "Catalyst system efficiency below threshold (Bank 1)",
    "P0430": "Catalyst system efficiency below threshold (Bank 2)",
    "P0441": "EVAP system incorrect purge flow",
    "P0442": "EVAP system small leak detected",
    "P0443": "EVAP purge control valve circuit malfunction",
    "P0446": "EVAP vent control circuit malfunction",
    "P0451": "EVAP pressure sensor range/performance",
    "P0455": "EVAP system large leak detected (loose gas cap)",
    "P0456": "EVAP system very small leak detected",
    # --- Idle / VTEC / electrical ---
    "P0505": "Idle air control system malfunction",
    "P0506": "Idle speed lower than expected",
    "P0507": "Idle speed higher than expected",
    "P0335": "Crankshaft position sensor A circuit",
    "P0339": "Crankshaft position sensor intermittent",
    "P0340": "Camshaft position sensor circuit",
    "P0341": "Camshaft position sensor range/performance",
    "P0327": "Knock sensor 1 low input (Bank 1)",
    "P0328": "Knock sensor 1 high input (Bank 1)",
    "P0420H": "",  # placeholder guard, never matched
    # --- VTC / oil pressure (K24 specific tendencies) ---
    "P0010": "Intake camshaft position actuator circuit (Bank 1)",
    "P0011": "Intake camshaft timing over-advanced (Bank 1)",
    "P0014": "Exhaust camshaft timing over-advanced (Bank 1)",
    "P0017": "Crank/cam position correlation (Bank 1 Sensor B)",
    "P0521": "Engine oil pressure sensor range/performance",
    # --- Transmission ---
    "P0700": "Transmission control system malfunction",
    "P0715": "Input/turbine speed sensor circuit",
    "P0720": "Output speed sensor circuit",
    "P0730": "Incorrect gear ratio",
    "P0740": "Torque converter clutch circuit malfunction",
    "P0780": "Shift malfunction",
    # --- Charging / battery ---
    "P0560": "System voltage malfunction",
    "P0562": "System voltage low",
    "P0563": "System voltage high",
    # --- Network ---
    "U0073": "Control module communication bus A off",
    "U0100": "Lost communication with ECM/PCM A",
    "U0101": "Lost communication with TCM",
    "U0121": "Lost communication with ABS control module",
    # --- Honda manufacturer-specific (P1xxx) commonly seen on Accords ---
    "P1009": "VTC advance malfunction",
    "P1077": "IMRC / intake manifold runner control (low rpm)",
    "P1078": "IMRC / intake manifold runner control (high rpm)",
    "P1106": "Barometric pressure circuit range/performance (Honda)",
    "P1128": "MAP lower than expected (Honda)",
    "P1129": "MAP higher than expected (Honda)",
    "P1157": "Air-fuel ratio sensor circuit (Honda)",
    "P1259": "VTEC system malfunction (Honda)",
    "P1361": "TDC sensor intermittent interruption (Honda)",
    "P1362": "TDC sensor no signal (Honda)",
    "P1456": "EVAP emission control - fuel tank system leak (Honda)",
    "P1457": "EVAP emission control - canister system leak (Honda)",
    "P1486": "Thermostat range/performance (Honda)",
    "P1659": "VTEC oil pressure switch (Honda)",
}
