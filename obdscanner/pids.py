"""
OBD-II Mode 01 (current data) PID table and decoders.

Each entry maps a PID number to (name, unit, n_bytes, decode_fn).
The decode function receives the list of integer data bytes (A, B, C, D...)
and returns a numeric or string value.

Formulas follow the SAE J1979 standard and apply to the Honda Accord 8th gen
(K24 2.4L) the same as any OBD-II compliant car.
"""

from __future__ import annotations


def _u(b, i):  # safe byte access
    return b[i] if i < len(b) else 0


# decode helpers ----------------------------------------------------------
def _percent(b):            return round(_u(b, 0) * 100.0 / 255.0, 1)
def _temp(b):               return _u(b, 0) - 40
def _fueltrim(b):           return round((_u(b, 0) - 128) * 100.0 / 128.0, 1)
def _fuelpress(b):          return _u(b, 0) * 3
def _map(b):                return _u(b, 0)
def _rpm(b):                return round((_u(b, 0) * 256 + _u(b, 1)) / 4.0, 0)
def _speed(b):              return _u(b, 0)
def _timing(b):             return round(_u(b, 0) / 2.0 - 64, 1)
def _maf(b):                return round((_u(b, 0) * 256 + _u(b, 1)) / 100.0, 2)
def _runtime(b):            return _u(b, 0) * 256 + _u(b, 1)
def _distance(b):           return _u(b, 0) * 256 + _u(b, 1)
def _ctrl_voltage(b):       return round((_u(b, 0) * 256 + _u(b, 1)) / 1000.0, 3)
def _abs_load(b):           return round((_u(b, 0) * 256 + _u(b, 1)) * 100.0 / 255.0, 1)
def _o2_voltage(b):         return round(_u(b, 0) / 200.0, 3)
def _fuel_rail_p(b):        return round((_u(b, 0) * 256 + _u(b, 1)) * 0.079, 1)
def _fuel_rail_p_direct(b): return (_u(b, 0) * 256 + _u(b, 1)) * 10
def _evap_press(b):         return round(((_u(b, 0) * 256 + _u(b, 1)) - 32767) / 4.0, 1)
def _baro(b):               return _u(b, 0)
def _commanded_egr(b):      return round(_u(b, 0) * 100.0 / 255.0, 1)
def _cat_temp(b):           return round((_u(b, 0) * 256 + _u(b, 1)) / 10.0 - 40, 1)
def _equiv_ratio(b):        return round((_u(b, 0) * 256 + _u(b, 1)) / 32768.0, 4)
# Wide-band O2 sensors report 4 bytes: AB = equivalence ratio (λ), CD = an
# extra channel (voltage on 0x24-0x2B, current on 0x34-0x3B). We surface λ as
# the primary value since that is what fuel-control analysis cares about.
def _wb_lambda(b):          return round((_u(b, 0) * 256 + _u(b, 1)) / 32768.0, 4)
def _ethanol(b):            return _percent(b)
def _abs_press(b):          return round((_u(b, 0) * 256 + _u(b, 1)) / 200.0, 2)


# Fuel system status (PID 03): byte A is a bit-encoded loop status.
_FUEL_SYS = {
    0x00: "off", 0x01: "open (warm-up)", 0x02: "closed loop",
    0x04: "open (load/decel)", 0x08: "open (fault)", 0x10: "closed (fault)",
}
def _fuel_status(b):
    a = _u(b, 0)
    return _FUEL_SYS.get(a, f"0x{a:02X}")


# PID table:  pid -> (name, unit, n_bytes, decoder)
PIDS = {
    0x03: ("Fuel system status", "", 2, _fuel_status),
    0x04: ("Calculated engine load", "%", 1, _percent),
    0x05: ("Engine coolant temp", "°C", 1, _temp),
    0x06: ("Short term fuel trim B1", "%", 1, _fueltrim),
    0x07: ("Long term fuel trim B1", "%", 1, _fueltrim),
    0x08: ("Short term fuel trim B2", "%", 1, _fueltrim),
    0x09: ("Long term fuel trim B2", "%", 1, _fueltrim),
    0x0A: ("Fuel pressure", "kPa", 1, _fuelpress),
    0x0B: ("Intake manifold pressure", "kPa", 1, _map),
    0x0C: ("Engine RPM", "rpm", 2, _rpm),
    0x0D: ("Vehicle speed", "km/h", 1, _speed),
    0x0E: ("Timing advance", "°", 1, _timing),
    0x0F: ("Intake air temp", "°C", 1, _temp),
    0x10: ("MAF air flow", "g/s", 2, _maf),
    0x11: ("Throttle position", "%", 1, _percent),
    0x14: ("O2 S1 voltage", "V", 2, _o2_voltage),
    0x15: ("O2 S2 voltage", "V", 2, _o2_voltage),
    0x16: ("O2 S3 voltage", "V", 2, _o2_voltage),
    0x17: ("O2 S4 voltage", "V", 2, _o2_voltage),
    0x18: ("O2 S5 voltage", "V", 2, _o2_voltage),
    0x19: ("O2 S6 voltage", "V", 2, _o2_voltage),
    0x1F: ("Run time since start", "s", 2, _runtime),
    0x21: ("Distance with MIL on", "km", 2, _distance),
    0x22: ("Fuel rail pressure (vac)", "kPa", 2, _fuel_rail_p),
    0x23: ("Fuel rail gauge pressure", "kPa", 2, _fuel_rail_p_direct),
    0x24: ("O2 S1 wide-range λ", "λ", 4, _wb_lambda),
    0x25: ("O2 S2 wide-range λ", "λ", 4, _wb_lambda),
    0x26: ("O2 S3 wide-range λ", "λ", 4, _wb_lambda),
    0x27: ("O2 S4 wide-range λ", "λ", 4, _wb_lambda),
    0x28: ("O2 S5 wide-range λ", "λ", 4, _wb_lambda),
    0x29: ("O2 S6 wide-range λ", "λ", 4, _wb_lambda),
    0x2C: ("Commanded EGR", "%", 1, _commanded_egr),
    0x2E: ("Commanded evap purge", "%", 1, _percent),
    0x2F: ("Fuel tank level", "%", 1, _percent),
    0x31: ("Distance since codes cleared", "km", 2, _distance),
    0x32: ("Evap system vapor pressure", "Pa", 2, _evap_press),
    0x33: ("Barometric pressure", "kPa", 1, _baro),
    0x34: ("Equivalence ratio S1", "λ", 2, _equiv_ratio),
    0x42: ("Control module voltage", "V", 2, _ctrl_voltage),
    0x43: ("Absolute load value", "%", 2, _abs_load),
    0x44: ("Commanded equiv ratio", "λ", 2, _equiv_ratio),
    0x45: ("Relative throttle position", "%", 1, _percent),
    0x46: ("Ambient air temp", "°C", 1, _temp),
    0x47: ("Absolute throttle pos B", "%", 1, _percent),
    0x49: ("Accelerator pedal pos D", "%", 1, _percent),
    0x4A: ("Accelerator pedal pos E", "%", 1, _percent),
    0x4C: ("Commanded throttle actuator", "%", 1, _percent),
    0x4D: ("Time run with MIL on", "min", 2, _runtime),
    0x4E: ("Time since codes cleared", "min", 2, _runtime),
    0x52: ("Ethanol fuel %", "%", 1, _ethanol),
    0x59: ("Fuel rail absolute pressure", "kPa", 2, lambda b: (_u(b, 0) * 256 + _u(b, 1)) * 10),
    0x5A: ("Relative accelerator pedal", "%", 1, _percent),
    0x5B: ("Hybrid battery remaining", "%", 1, _percent),
    0x5C: ("Engine oil temp", "°C", 1, _temp),
    0x5E: ("Engine fuel rate", "L/h", 2, lambda b: round((_u(b, 0) * 256 + _u(b, 1)) * 0.05, 2)),
    0x63: ("Engine reference torque", "Nm", 2, lambda b: _u(b, 0) * 256 + _u(b, 1)),
    0x67: ("Engine coolant temp (2)", "°C", 2, lambda b: _u(b, 1) - 40),
}


def decode(pid: int, data_bytes: list[int]):
    """Return (name, value, unit) for a Mode-01 PID, or None if unknown."""
    entry = PIDS.get(pid)
    if entry is None:
        return None
    name, unit, _n, fn = entry
    try:
        value = fn(data_bytes)
    except Exception:
        value = None
    return name, value, unit


# A sensible default set for the live dashboard (only the ones the ECU
# actually reports are shown; the rest are skipped automatically).
DASHBOARD_PIDS = [
    0x0C, 0x0D, 0x05, 0x0F, 0x04, 0x11, 0x10,
    0x06, 0x07, 0x0E, 0x0B, 0x33, 0x2F, 0x42,
]
