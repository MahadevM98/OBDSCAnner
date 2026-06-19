"""
Full vehicle data extraction: one pass that pulls every piece of information the
adapter can reach and returns it as an ordered, serialisable report. Used by the
"Full Extract" tab and its TXT/JSON export.

Sections gathered:
  adapter / protocol / voltage      (session info)
  VIN, calibration id, CVN, ECU     (Mode 09)
  readiness monitors + MIL          (Mode 01 PID 01)
  every supported live PID          (Mode 01)
  stored / pending / permanent DTCs (Mode 03 / 07 / 0A)
  freeze frame                      (Mode 02)
  on-board monitor results          (Mode 06)
  Honda enhanced parameters         (Mode 22, experimental)
"""

from __future__ import annotations

import datetime as _dt
import json

from . import pids as pids_mod


def full_extract(elm, progress=None) -> dict:
    """Run the whole read sequence against a live ELM327.

    `progress(label)` is called before each section so the GUI can show what is
    happening. Every section is wrapped so one unsupported service never aborts
    the rest of the dump.
    """
    def step(label, fn, default):
        if progress:
            progress(label)
        try:
            return fn()
        except Exception as e:  # never let one service kill the whole report
            return default if not isinstance(default, dict) else {
                **default, "_error": str(e)}

    report: dict = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    report["session"] = step("Session info", lambda: {
        "Adapter": elm.adapter_id,
        "Protocol": elm.protocol,
        "Battery voltage": elm.read_voltage(),
    }, {})

    report["vehicle"] = step("Vehicle info (Mode 09)", lambda: {
        "VIN": elm.read_vin() or "(not reported)",
        **elm.read_vehicle_info(),
    }, {})

    report["readiness"] = step("Readiness monitors", elm.read_monitors, {})

    def _sensors():
        rows = []
        for pid in sorted(elm.supported_pids()):
            if pid not in pids_mod.PIDS:
                continue
            r = elm.query_pid(pid)
            if r is not None:
                name, value, unit = r
                rows.append({"pid": f"0x{pid:02X}", "name": name,
                             "value": value, "unit": unit})
        return rows
    report["live_data"] = step("Live sensors (Mode 01)", _sensors, [])

    report["dtc"] = step("Trouble codes", lambda: {
        "stored": elm.read_stored_dtcs(),
        "pending": elm.read_pending_dtcs(),
        "permanent": elm.read_permanent_dtcs(),
    }, {})

    report["freeze_frame"] = step("Freeze frame (Mode 02)",
                                  elm.read_freeze_frame, {})

    report["mode06"] = step("On-board monitors (Mode 06)",
                            lambda: [t.as_row() for t in elm.read_mode06()], [])

    report["honda_enhanced"] = step("Honda enhanced (Mode 22)",
                                    elm.read_honda_enhanced, [])

    return report


def to_text(report: dict) -> str:
    """Render a report as a readable plain-text diagnostic dump."""
    L = []
    w = L.append
    w("=" * 60)
    w("  OBD-II FULL VEHICLE EXTRACT")
    w(f"  Generated: {report.get('generated', '?')}")
    w("=" * 60)

    def section(title):
        w("")
        w(f"--- {title} ---")

    for title, key in (("SESSION", "session"), ("VEHICLE", "vehicle"),
                       ("READINESS MONITORS", "readiness")):
        section(title)
        for k, v in (report.get(key) or {}).items():
            w(f"  {k:<32} {v}")

    section("LIVE SENSORS (Mode 01)")
    for row in report.get("live_data") or []:
        w(f"  {row['name']:<32} {row['value']} {row['unit']}".rstrip())

    section("TROUBLE CODES")
    dtc = report.get("dtc") or {}
    for kind in ("stored", "pending", "permanent"):
        codes = dtc.get(kind) or []
        w(f"  {kind.capitalize()}: " + ("none" if not codes else ""))
        for code, desc in codes:
            w(f"    {code}  {desc}")

    section("FREEZE FRAME (Mode 02)")
    ff = report.get("freeze_frame") or {}
    w(f"  Triggered by DTC: {ff.get('dtc') or '(none)'}")
    for pid, name, value, unit in ff.get("values") or []:
        w(f"  {name:<32} {value} {unit}".rstrip())

    section("ON-BOARD MONITORS (Mode 06)")
    rows = report.get("mode06") or []
    if not rows:
        w("  none reported")
    for name, tid, value, lo, hi, verdict in rows:
        w(f"  [{verdict}] {name:<28} TID {tid}  val={value} "
          f"min={lo} max={hi}")

    section("HONDA ENHANCED (Mode 22, experimental)")
    he = report.get("honda_enhanced") or []
    if not he:
        w("  none reported")
    for name, value, unit in he:
        w(f"  {name:<32} {value} {unit}".rstrip())

    w("")
    return "\n".join(L)


def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, default=str)
