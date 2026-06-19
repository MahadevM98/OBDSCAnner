"""
A minimal real-time strip chart drawn on a tkinter Canvas.

No third-party plotting libraries — the app stays stdlib-only. Each chart shows
one sensor over a rolling time window, auto-scales the Y axis to the data (and
to the Accord spec band when one is given), shades the normal range, and prints
the current / min / max values.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

_BG = "#0e1116"
_GRID = "#23303a"
_LINE = "#4fd0ff"
_BAND = "#16321f"
_TEXT = "#c7d0d8"
_MUTED = "#6b7a86"


class StripChart(ttk.Frame):
    def __init__(self, master, title="", unit="", spec=None,
                 width=640, height=120, window_s=120.0):
        super().__init__(master)
        self.title = title
        self.unit = unit
        self.spec = spec            # (normal_lo, normal_hi) or None
        self.window_s = window_s
        self.cw = width
        self.ch = height
        self.canvas = tk.Canvas(self, width=width, height=height,
                                background=_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

    def redraw(self, times: list[float], values: list) -> None:
        c = self.canvas
        c.delete("all")
        w, h = self.cw, self.ch
        pad_l, pad_r, pad_t, pad_b = 56, 10, 18, 16
        x0, x1 = pad_l, w - pad_r
        y0, y1 = pad_t, h - pad_b

        # Restrict to the trailing time window.
        pts = [(t, v) for t, v in zip(times, values) if v is not None]
        t_end = times[-1] if times else 0.0
        t_start = t_end - self.window_s
        win = [(t, v) for t, v in pts if t >= t_start]

        finite = [v for _t, v in win]
        lo_band = hi_band = None
        if self.spec:
            lo_band, hi_band = self.spec
        ys = list(finite)
        for b in (lo_band, hi_band):
            if isinstance(b, (int, float)):
                ys.append(b)
        if ys:
            ymin, ymax = min(ys), max(ys)
        else:
            ymin, ymax = 0.0, 1.0
        if ymax - ymin < 1e-6:
            ymin -= 1.0
            ymax += 1.0
        margin = (ymax - ymin) * 0.1
        ymin -= margin
        ymax += margin

        def sx(t):
            span = self.window_s or 1.0
            return x0 + (t - t_start) / span * (x1 - x0)

        def sy(v):
            return y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)

        # Normal-range shaded band.
        if isinstance(lo_band, (int, float)) and isinstance(hi_band, (int, float)):
            c.create_rectangle(x0, sy(hi_band), x1, sy(lo_band),
                               fill=_BAND, outline="")

        # Frame + min/max guide lines.
        c.create_rectangle(x0, y0, x1, y1, outline=_GRID)
        c.create_line(x0, y0, x1, y0, fill=_GRID)
        c.create_text(x0 - 4, y0, text=_fmt(ymax), anchor="e",
                      fill=_MUTED, font=("TkDefaultFont", 7))
        c.create_text(x0 - 4, y1, text=_fmt(ymin), anchor="e",
                      fill=_MUTED, font=("TkDefaultFont", 7))

        # The trace.
        if len(win) >= 2:
            coords = []
            for t, v in win:
                coords.extend((sx(t), sy(v)))
            c.create_line(*coords, fill=_LINE, width=2)
        elif len(win) == 1:
            t, v = win[0]
            c.create_oval(sx(t) - 2, sy(v) - 2, sx(t) + 2, sy(v) + 2,
                          fill=_LINE, outline="")

        # Title + current value.
        cur = finite[-1] if finite else None
        cur_txt = f"{_fmt(cur)} {self.unit}".strip() if cur is not None else "—"
        c.create_text(x0, 9, text=self.title, anchor="w", fill=_TEXT,
                      font=("TkDefaultFont", 8, "bold"))
        c.create_text(x1, 9, text=cur_txt, anchor="e", fill=_LINE,
                      font=("TkDefaultFont", 9, "bold"))


def _fmt(n) -> str:
    if n is None:
        return "—"
    if isinstance(n, float):
        return f"{n:.1f}" if abs(n) < 100 else f"{n:.0f}"
    return str(n)
