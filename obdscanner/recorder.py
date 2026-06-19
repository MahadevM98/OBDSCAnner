"""
Time-series recorder for live sensor data.

Holds a rolling buffer of decoded sensor values keyed by Mode-01 PID, all
sharing one timeline so the data can be drawn as strip charts and exported as
a single tidy CSV (one column per sensor, one row per sample).

Pure logic — no tkinter — so it is unit-testable offline.
"""

from __future__ import annotations

import io
import time
from collections import deque


class Recorder:
    def __init__(self, max_points: int = 7200):
        # ~7200 samples ≈ 30 min at 4 Hz before the oldest points roll off.
        self.max_points = max_points
        self.pids: list[int] = []
        self.times: deque[float] = deque(maxlen=max_points)
        self.series: dict[int, deque] = {}
        self._t0: float | None = None

    def set_pids(self, pids) -> None:
        """Choose which PIDs to track. Resets any captured data."""
        self.pids = list(pids)
        self.clear()

    def clear(self) -> None:
        self.times.clear()
        self.series = {p: deque(maxlen=self.max_points) for p in self.pids}
        self._t0 = None

    def add_snapshot(self, values: dict, t: float | None = None) -> None:
        """Append one timestamped sample. `values` maps pid -> number; any
        tracked PID missing from it (or non-numeric) is stored as a gap."""
        if not self.pids:
            return
        t = time.monotonic() if t is None else t
        if self._t0 is None:
            self._t0 = t
        self.times.append(t - self._t0)
        for p in self.pids:
            v = values.get(p)
            self.series.setdefault(p, deque(maxlen=self.max_points)).append(
                v if isinstance(v, (int, float)) else None)

    def latest(self, pid: int):
        """Most recent non-gap value for a PID, or None."""
        for v in reversed(self.series.get(pid, ())):
            if v is not None:
                return v
        return None

    def get(self, pid: int) -> tuple[list[float], list]:
        """Return (relative_times, values) for a PID, aligned by index."""
        return list(self.times), list(self.series.get(pid, ()))

    def __len__(self) -> int:
        return len(self.times)

    def to_csv(self) -> str:
        """Render the whole buffer as CSV text (header = sensor names)."""
        import csv

        from . import pids as pids_mod

        buf = io.StringIO()
        w = csv.writer(buf)
        header = ["time_s"]
        for p in self.pids:
            name, unit = pids_mod.PIDS.get(p, (f"PID {p:02X}", ""))[:2]
            header.append(f"{name} ({unit})" if unit else name)
        w.writerow(header)
        cols = [list(self.series.get(p, [])) for p in self.pids]
        for i, t in enumerate(self.times):
            row = [f"{t:.2f}"]
            for col in cols:
                row.append("" if i >= len(col) or col[i] is None else col[i])
            w.writerow(row)
        return buf.getvalue()
