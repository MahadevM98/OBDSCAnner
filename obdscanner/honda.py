"""
Honda manufacturer-specific (enhanced) parameters via OBD service Mode 22.

IMPORTANT: these are EXPERIMENTAL. Unlike the generic SAE PIDs in pids.py,
Honda's enhanced Mode 22 PIDs are not publicly standardised; the exact PID
numbers and scaling vary by model year and ECU, and many ELM327 clones cannot
address them at all. The reader below is best-effort: it asks for each candidate
and simply skips anything the ECU does not answer, so on a car that does not
support a PID you get nothing (rather than a wrong value).

Treat any value shown as a starting point to confirm against Honda service
data — do not rely on it for a diagnosis. Correct the table here once you have
verified PIDs for your specific car.
"""

from __future__ import annotations


def _u(b, i):
    return b[i] if i < len(b) else 0


# Mode 22 PID -> (name, unit, min_bytes, decoder). EXPERIMENTAL candidates.
ENHANCED: dict[int, tuple] = {
    0x1101: ("VTC cam advance angle", "°", 1, lambda b: round(_u(b, 0) / 2.0, 1)),
    0x1102: ("Knock retard", "°", 1, lambda b: round(_u(b, 0) / 2.0, 1)),
    0x1103: ("Knock count", "", 1, lambda b: _u(b, 0)),
    0x1104: ("VTEC oil pressure switch", "", 1,
             lambda b: "ON" if _u(b, 0) else "off"),
    0x115C: ("Transmission fluid temp", "°C", 1, lambda b: _u(b, 0) - 40),
}
