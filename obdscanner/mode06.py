"""
Mode 06 - On-board monitoring test results (the data emissions test stations
read). Each result is identified by an OBDMID (monitor id) and a TID (test id),
and carries a measured test value plus the min/max limits the ECU judged it by.

Honesty note: the physical unit/scaling of the value+limits is selected by a
per-test "Unit And Scaling" (UAS) id whose full table is large and ECU-specific.
Rather than risk showing a wrongly-scaled number, we report the RAW measured
value alongside its raw min/max limits and a scale-invariant PASS/FAIL verdict
(min <= value <= max). That verdict is correct regardless of scaling as long as
the three share a UAS id, which they always do. The MID names below are the
standardised SAE J1979 monitor ids; anything unlisted falls back to its hex id.
"""

from __future__ import annotations

# Standardised OBDMID -> human name (SAE J1979). Manufacturer-specific MIDs
# (typically >= 0xA0) are shown by their hex id.
MID_NAMES = {
    0x01: "O2 Sensor Monitor B1S1",
    0x02: "O2 Sensor Monitor B1S2",
    0x03: "O2 Sensor Monitor B1S3",
    0x04: "O2 Sensor Monitor B1S4",
    0x05: "O2 Sensor Monitor B2S1",
    0x06: "O2 Sensor Monitor B2S2",
    0x07: "O2 Sensor Monitor B2S3",
    0x08: "O2 Sensor Monitor B2S4",
    0x21: "Catalyst Monitor Bank 1",
    0x22: "Catalyst Monitor Bank 2",
    0x31: "EGR Monitor Bank 1",
    0x32: "EGR Monitor Bank 2",
    0x39: "EVAP Monitor (Cap Off / large leak)",
    0x3A: "EVAP Monitor (0.090\")",
    0x3B: "EVAP Monitor (0.040\")",
    0x3C: "EVAP Monitor (0.020\")",
    0x3D: "Purge Flow Monitor",
    0x41: "O2 Heater Monitor B1S1",
    0x42: "O2 Heater Monitor B1S2",
    0x43: "O2 Heater Monitor B1S3",
    0x44: "O2 Heater Monitor B1S4",
    0x45: "O2 Heater Monitor B2S1",
    0x46: "O2 Heater Monitor B2S2",
    0x47: "O2 Heater Monitor B2S3",
    0x48: "O2 Heater Monitor B2S4",
}


def mid_name(mid: int) -> str:
    return MID_NAMES.get(mid, f"Monitor 0x{mid:02X}")


class TestResult:
    """One Mode-06 test result line."""
    __slots__ = ("mid", "tid", "uas", "value", "lo", "hi")

    def __init__(self, mid, tid, uas, value, lo, hi):
        self.mid = mid
        self.tid = tid
        self.uas = uas
        self.value = value   # raw measured value
        self.lo = lo         # raw min limit
        self.hi = hi         # raw max limit

    @property
    def passed(self) -> bool:
        return self.lo <= self.value <= self.hi

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def as_row(self) -> tuple:
        return (mid_name(self.mid), f"0x{self.tid:02X}",
                str(self.value), str(self.lo), str(self.hi), self.verdict)


def parse(data: list[int]) -> list[TestResult]:
    """Parse the flattened payload that follows the 0x46 mode byte on CAN.

    CAN layout per record (9 bytes): MID TID UAS V_hi V_lo MIN_hi MIN_lo
    MAX_hi MAX_lo. We require the full 9-byte stride and stop on anything
    short so a truncated multi-frame reply never yields garbage rows.
    """
    out: list[TestResult] = []
    i = 0
    n = len(data)
    while i + 9 <= n:
        mid, tid, uas = data[i], data[i + 1], data[i + 2]
        value = (data[i + 3] << 8) | data[i + 4]
        lo = (data[i + 5] << 8) | data[i + 6]
        hi = (data[i + 7] << 8) | data[i + 8]
        # MID 0x00 is the "supported MIDs" bitmap, not a result row.
        if mid != 0x00:
            out.append(TestResult(mid, tid, uas, value, lo, hi))
        i += 9
    return out
