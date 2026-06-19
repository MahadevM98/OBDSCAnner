"""
Vehicle-specific spec ranges and automatic health analysis for the
Honda Accord 8th generation 2.4L (K24, model years ~2008-2012).

Two parts:

  SPECS / status_for() - typical warm-engine operating range for each Mode-01
        PID. Used to flag a live reading green / amber / red so a value shows
        next to "what it should be" for this engine.

  analyze_*()          - interpret a one-shot snapshot of sensor readings into
        plain-language verdicts (Normal / Suspect / Fault likely), backing the
        Engine Health and Pre-Purchase Inspection screens.

These ranges are typical guidance values for this engine, not a substitute for
the factory service manual. A reading inside the "normal" band is reassuring;
one outside it is a prompt to look closer, not proof of a fault.
"""

from __future__ import annotations

from collections import namedtuple

# --- status levels -------------------------------------------------------
NORMAL = "Normal"
SUSPECT = "Suspect"
FAULT = "Fault likely"
UNKNOWN = "—"

# Ordering so we can take the "worst" status across several checks.
_RANK = {UNKNOWN: 0, NORMAL: 1, SUSPECT: 2, FAULT: 3}


def worst(*statuses: str) -> str:
    """Return the most serious status among the arguments."""
    return max((s for s in statuses), key=lambda s: _RANK.get(s, 0), default=UNKNOWN)


# A spec band: values inside [normal_lo, normal_hi] are normal; inside the
# wider [abs_lo, abs_hi] but outside normal are suspect; beyond abs are a
# likely fault. Use None for a bound that does not apply (e.g. no high limit).
Spec = namedtuple("Spec", "normal_lo normal_hi abs_lo abs_hi note")


# PID -> Spec. Warm-engine, idle-biased values for the K24 2.4L.
SPECS: dict[int, Spec] = {
    0x04: Spec(10, 90, None, 100, "Idle 15-35%, WOT ~85-95%"),
    0x05: Spec(80, 98, None, 110, "Thermostat opens ~90°C; >110 = overheating"),
    0x06: Spec(-10, 10, -20, 20, "Short-term fuel trim; ±10% normal, >±20% fault"),
    0x07: Spec(-10, 10, -20, 20, "Long-term fuel trim; ±10% normal, >±20% fault"),
    0x08: Spec(-10, 10, -20, 20, "Bank 2 (4-cyl: usually n/a)"),
    0x09: Spec(-10, 10, -20, 20, "Bank 2 (4-cyl: usually n/a)"),
    0x0B: Spec(20, 45, 15, 105, "Idle 25-40 kPa (high vacuum); WOT ~baro"),
    0x0C: Spec(650, 850, 450, 6800, "Warm idle 650-850 rpm; redline ~6800"),
    0x0E: Spec(5, 25, -10, 55, "Idle timing advance, degrees BTDC"),
    0x0F: Spec(-10, 60, -20, 90, "Intake air temp (near ambient)"),
    0x10: Spec(2, 8, 0, 250, "Idle 2-5 g/s; rises with load"),
    0x11: Spec(8, 22, 0, 100, "Idle throttle ~10-16%"),
    0x14: Spec(0.1, 0.9, 0.0, 1.1, "Upstream O2 should swing 0.1-0.9V"),
    0x15: Spec(0.3, 0.9, 0.0, 1.1, "Downstream O2 fairly steady if cat OK"),
    0x33: Spec(90, 102, 70, 110, "Barometric pressure (lower at altitude)"),
    0x42: Spec(13.5, 14.8, 13.0, 15.1, "Charging voltage, engine running"),
    0x46: Spec(-10, 50, -40, 90, "Ambient air temp"),
    0x5C: Spec(80, 110, 60, 130, "Engine oil temp"),
}


def status_for(pid: int, value) -> str:
    """Classify a live reading against the Accord spec band for that PID."""
    spec = SPECS.get(pid)
    if spec is None or not isinstance(value, (int, float)):
        return UNKNOWN
    if spec.abs_lo is not None and value < spec.abs_lo:
        return FAULT
    if spec.abs_hi is not None and value > spec.abs_hi:
        return FAULT
    if spec.normal_lo is not None and value < spec.normal_lo:
        return SUSPECT
    if spec.normal_hi is not None and value > spec.normal_hi:
        return SUSPECT
    return NORMAL


def range_text(pid: int) -> str:
    """Human 'normal range' string for a PID, e.g. '80–98' or '≤ 100'."""
    spec = SPECS.get(pid)
    if spec is None:
        return ""
    lo, hi = spec.normal_lo, spec.normal_hi
    if lo is not None and hi is not None:
        return f"{_fmt(lo)}–{_fmt(hi)}"
    if hi is not None:
        return f"≤ {_fmt(hi)}"
    if lo is not None:
        return f"≥ {_fmt(lo)}"
    return ""


def _fmt(n) -> str:
    if isinstance(n, float) and n != int(n):
        return f"{n:g}"
    return str(int(n))


# --- automatic health analysis ------------------------------------------
# Each analyzer takes a snapshot dict {pid: value} (values already decoded by
# pids.decode) and returns (status, detail_text).

Finding = namedtuple("Finding", "category status detail")


def _get(snap, pid):
    v = snap.get(pid)
    return v if isinstance(v, (int, float)) else None


def analyze_fuel_trim(snap) -> Finding:
    stft = _get(snap, 0x06)
    ltft = _get(snap, 0x07)
    if stft is None and ltft is None:
        return Finding("Fuel Trim", UNKNOWN, "Fuel trim PIDs not reported.")
    total = (stft or 0) + (ltft or 0)
    direction = "rich" if total < 0 else "lean"
    mag = abs(total)
    if mag <= 10:
        st = NORMAL
        msg = f"Combined trim {total:+.1f}% — within ±10%."
    elif mag <= 20:
        st = SUSPECT
        msg = (f"Combined trim {total:+.1f}% (running {direction}). "
               "Watch for small leaks, dirty MAF, or weak fuel delivery.")
    else:
        st = FAULT
        msg = (f"Combined trim {total:+.1f}% (strongly {direction}). "
               + ("Suspect vacuum leak / lean fault."
                  if direction == "lean"
                  else "Suspect leaking injector / high fuel pressure."))
    return Finding("Fuel Trim", st, msg)


def analyze_vacuum_leak(snap) -> Finding:
    stft = _get(snap, 0x06)
    ltft = _get(snap, 0x07)
    rpm = _get(snap, 0x0C)
    mapv = _get(snap, 0x0B)
    if stft is None or ltft is None:
        return Finding("Vacuum Leak", UNKNOWN, "Need fuel trims to evaluate.")
    at_idle = rpm is None or rpm < 1100
    total = stft + ltft
    # A vacuum leak shows as a strong positive (lean) trim at idle, often with
    # higher-than-expected manifold pressure (less vacuum).
    map_high = mapv is not None and mapv > 45
    if at_idle and total > 12 and (map_high or mapv is None):
        return Finding(
            "Vacuum Leak", FAULT,
            f"Lean trim {total:+.1f}% at idle"
            + (f" with high MAP {mapv:.0f} kPa" if map_high else "")
            + " — vacuum/intake leak suspected.")
    if at_idle and total > 8:
        return Finding("Vacuum Leak", SUSPECT,
                       f"Mildly lean ({total:+.1f}%) at idle — monitor.")
    return Finding("Vacuum Leak", NORMAL, "No lean-at-idle pattern.")


def analyze_map(snap) -> Finding:
    """Intake manifold pressure check. At warm idle the K24 pulls strong
    vacuum (25-40 kPa); at wide-open throttle MAP rises to near barometric."""
    mapv = _get(snap, 0x0B)
    rpm = _get(snap, 0x0C)
    baro = _get(snap, 0x33)
    if mapv is None:
        return Finding("MAP Sensor", UNKNOWN, "Manifold pressure not reported.")
    if rpm is not None and rpm < 1100:
        if mapv > 45:
            return Finding("MAP Sensor", SUSPECT,
                           f"Idle MAP {mapv:.0f} kPa is high (expect 25-40) — "
                           "weak vacuum: vacuum leak or sensor.")
        if mapv < 20:
            return Finding("MAP Sensor", SUSPECT,
                           f"Idle MAP {mapv:.0f} kPa is low (expect 25-40) — "
                           "check sensor / hose.")
        return Finding("MAP Sensor", NORMAL,
                       f"Idle MAP {mapv:.0f} kPa within the 25-40 kPa range.")
    ceiling = (baro or 105) + 5
    if mapv > ceiling:
        return Finding("MAP Sensor", SUSPECT,
                       f"MAP {mapv:.0f} kPa above barometric — check sensor.")
    return Finding("MAP Sensor", NORMAL,
                   f"MAP {mapv:.0f} kPa (off-idle; near atmospheric under load).")


def analyze_ignition_timing(snap) -> Finding:
    adv = _get(snap, 0x0E)
    rpm = _get(snap, 0x0C)
    if adv is None:
        return Finding("Ignition Timing", UNKNOWN, "Timing advance not reported.")
    if rpm is not None and rpm < 1100 and adv < 2:
        return Finding("Ignition Timing", SUSPECT,
                       f"Only {adv:.0f}° advance at idle — timing not advancing.")
    if adv < -5:
        return Finding("Ignition Timing", SUSPECT,
                       f"Timing retarded {adv:.0f}° — possible knock pull / fuel quality.")
    return Finding("Ignition Timing", NORMAL, f"Advance {adv:.0f}° looks normal.")


def analyze_cooling(snap) -> Finding:
    t = _get(snap, 0x05)
    if t is None:
        return Finding("Cooling System", UNKNOWN, "Coolant temp not reported.")
    if t > 105:
        return Finding("Cooling System", FAULT, f"Coolant {t:.0f}°C — overheating.")
    if t < 70:
        return Finding("Cooling System", SUSPECT,
                       f"Coolant {t:.0f}°C — not at operating temp (warming up?).")
    if t > 100:
        return Finding("Cooling System", SUSPECT, f"Coolant {t:.0f}°C — running warm.")
    return Finding("Cooling System", NORMAL, f"Coolant {t:.0f}°C — normal range.")


def analyze_charging(snap) -> Finding:
    v = _get(snap, 0x42)
    if v is None:
        return Finding("Charging System", UNKNOWN, "Module voltage not reported.")
    if v < 13.0:
        return Finding("Charging System", FAULT if v < 12.4 else SUSPECT,
                       f"{v:.1f}V — undercharging (weak alternator/battery?).")
    if v > 15.1:
        return Finding("Charging System", FAULT,
                       f"{v:.1f}V — overcharging (voltage regulator fault).")
    if v > 14.8:
        return Finding("Charging System", SUSPECT, f"{v:.1f}V — slightly high.")
    return Finding("Charging System", NORMAL, f"{v:.1f}V — charging normally.")


def analyze_o2(snap) -> Finding:
    up = _get(snap, 0x14)
    down = _get(snap, 0x15)
    if up is None:
        return Finding("O2 Sensors", UNKNOWN, "Upstream O2 not reported.")
    # Snapshot only: we can sanity-check levels, not switching speed.
    if up < 0.05 or up > 1.05:
        return Finding("O2 Sensors", SUSPECT,
                       f"Upstream O2 stuck at {up:.2f}V — check sensor.")
    return Finding("O2 Sensors", NORMAL,
                   f"Upstream O2 {up:.2f}V"
                   + (f", downstream {down:.2f}V" if down is not None else "")
                   + " (live graph needed for switching speed).")


def analyze_catalyst(snap) -> Finding:
    """Snapshot heuristic: a healthy cat makes the downstream O2 hold steady
    near mid-band while the upstream swings. We can only flag the obvious
    case where downstream mirrors a high upstream."""
    up = _get(snap, 0x14)
    down = _get(snap, 0x15)
    load = _get(snap, 0x04)
    if up is None or down is None:
        return Finding("Catalytic Converter", UNKNOWN,
                       "Need both O2 sensors (use the live graph for a real test).")
    load_txt = f" at {load:.0f}% load" if load is not None else ""
    if down > 0.75 and up > 0.6:
        return Finding("Catalytic Converter", SUSPECT,
                       f"Downstream O2 tracking upstream high{load_txt} — "
                       "possible efficiency loss / restriction.")
    return Finding("Catalytic Converter", NORMAL,
                   f"Downstream O2 steady within range{load_txt} "
                   "(confirm with live monitor).")


# All snapshot analyzers, in display order.
HEALTH_ANALYZERS = [
    analyze_fuel_trim,
    analyze_vacuum_leak,
    analyze_ignition_timing,
    analyze_o2,
    analyze_catalyst,
    analyze_cooling,
    analyze_charging,
]


def analyze_all(snap) -> list[Finding]:
    """Run every snapshot analyzer and return the findings."""
    return [fn(snap) for fn in HEALTH_ANALYZERS]


# --- pre-purchase inspection scoring ------------------------------------
SCORE_LABELS = [(90, "Excellent"), (75, "Good"), (50, "Fair"), (0, "Poor")]


def _label_for(score: int) -> str:
    for threshold, label in SCORE_LABELS:
        if score >= threshold:
            return label
    return "Poor"


# Map a status to a points penalty for scoring.
_PENALTY = {NORMAL: 0, UNKNOWN: 0, SUSPECT: 12, FAULT: 30}


def inspection_report(snap, dtcs, monitors) -> dict:
    """Build a pre-purchase summary.

    snap     : {pid: value} snapshot
    dtcs     : {"stored": [...], "pending": [...], "permanent": [...]}
    monitors : readiness dict from ELM327.read_monitors()

    Returns {"sections": [(name, status, detail)], "score": int,
             "label": str, "dtc_total": int}.
    """
    findings = analyze_all(snap)
    by_cat = {f.category: f for f in findings}

    stored = dtcs.get("stored", [])
    pending = dtcs.get("pending", [])
    permanent = dtcs.get("permanent", [])
    all_codes = [c for c, _ in stored + pending + permanent]
    dtc_total = len(stored) + len(pending) + len(permanent)

    def has(prefixes):
        return any(c.startswith(p) for c in all_codes for p in prefixes)

    sections = []

    # Engine: misfire / lean / rich / sensor codes plus fuel-trim finding.
    eng_status = by_cat["Fuel Trim"].status
    eng_detail = by_cat["Fuel Trim"].detail
    if has(("P030",)):
        eng_status = worst(eng_status, FAULT)
        eng_detail = "Misfire code present. " + eng_detail
    elif has(("P01", "P02")):
        eng_status = worst(eng_status, SUSPECT)
        eng_detail = "Fuel/air metering code present. " + eng_detail
    sections.append(("Engine", eng_status, eng_detail))

    # Cooling
    sections.append(("Cooling System",) + _sect(by_cat["Cooling System"],
                                                 has(("P0116", "P0117", "P0118",
                                                      "P0128", "P1486")),
                                                 "Cooling code present."))
    # Fuel system
    fuel = by_cat["Vacuum Leak"]
    sections.append(("Fuel System",) + _sect(fuel,
                                             has(("P0171", "P0172", "P0174", "P0175")),
                                             "Lean/rich code present."))
    # Battery & charging
    sections.append(("Battery & Charging",) + _sect(by_cat["Charging System"],
                                                     has(("P0560", "P0562", "P0563")),
                                                     "Charging code present."))
    # Catalytic converter
    sections.append(("Catalytic Converter",) + _sect(by_cat["Catalytic Converter"],
                                                      has(("P0420", "P0430")),
                                                      "Catalyst efficiency code present."))
    # Transmission (DTC-only here)
    tx_status = FAULT if has(("P07",)) else NORMAL
    tx_detail = "Transmission code present." if tx_status == FAULT else "No transmission codes."
    sections.append(("Transmission", tx_status, tx_detail))

    # Score: start at 100, subtract section penalties and a per-DTC penalty.
    score = 100
    for _name, status, _detail in sections:
        score -= _PENALTY.get(status, 0)
    score -= min(dtc_total * 4, 20)
    if monitors.get("MIL (check engine lamp)") == "ON":
        score -= 10
    score = max(0, min(100, score))

    return {
        "sections": sections,
        "score": score,
        "label": _label_for(score),
        "dtc_total": dtc_total,
    }


def _sect(finding, code_present, code_msg):
    status = finding.status
    detail = finding.detail
    if code_present:
        status = worst(status, FAULT)
        detail = code_msg + " " + detail
    return status, detail
