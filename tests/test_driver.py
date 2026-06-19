"""Offline smoke test of the ELM327 driver against the fake ECU."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obdscanner.elm327 import ELM327          # noqa: E402
from obdscanner.dtc import decode_dtc          # noqa: E402
from obdscanner import analysis as an          # noqa: E402
from obdscanner import cards as cards_mod        # noqa: E402
from obdscanner.recorder import Recorder        # noqa: E402
from tests.fake_elm import FakeELMTransport    # noqa: E402


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        check.failed += 1
check.failed = 0


def main():
    t = FakeELMTransport()
    e = ELM327(t, read_timeout=2.0)
    e.t.open()
    info = e.initialize()
    check("adapter id parsed", "ELM327" in info["adapter"])
    check("protocol parsed", "CAN" in info["protocol"])
    check("voltage parsed", "13.9" in info["voltage"])

    # raw DTC decode unit check
    check("decode_dtc P0301", decode_dtc(0x03, 0x01) == "P0301")
    check("decode_dtc P0420", decode_dtc(0x04, 0x20) == "P0420")
    check("decode_dtc U0100", decode_dtc(0xC1, 0x00) == "U0100")
    check("decode_dtc padding None", decode_dtc(0x00, 0x00) is None)

    sup = e.supported_pids()
    check("supports RPM (0x0C)", 0x0C in sup)
    check("supports coolant (0x05)", 0x05 in sup)

    rpm = e.query_pid(0x0C)
    check("RPM decodes to 1000", rpm and abs(rpm[1] - 1000) < 1)
    speed = e.query_pid(0x0D)
    check("speed decodes to 40", speed and speed[1] == 40)
    coolant = e.query_pid(0x05)
    check("coolant decodes to 50C", coolant and coolant[1] == 50)
    volt = e.query_pid(0x42)
    check("module voltage ~14V", volt and abs(volt[1] - 14.0) < 0.1)

    stored = e.read_stored_dtcs()
    codes = [c for c, _ in stored]
    check("stored has P0301", "P0301" in codes)
    check("stored has P0420", "P0420" in codes)
    check("P0420 described", any("Catalyst" in d for _, d in stored))

    pending = e.read_pending_dtcs()
    check("pending has P0171", "P0171" in [c for c, _ in pending])

    perm = e.read_permanent_dtcs()
    check("permanent has P0420", "P0420" in [c for c, _ in perm])

    vin = e.read_vin()
    check("VIN read (17 chars)", len(vin) == 17 and vin.startswith("1HGCP"))

    mon = e.read_monitors()
    check("monitors include MIL", "MIL (check engine lamp)" in mon)

    ok = e.clear_dtcs()
    check("clear returns True", ok is True)
    after = e.read_stored_dtcs()
    check("stored empty after clear", after == [])

    # --- spec ranges / status (Honda Accord 8th gen 2.4L) ---
    check("coolant 88C is Normal", an.status_for(0x05, 88) == an.NORMAL)
    check("coolant 112C is Fault", an.status_for(0x05, 112) == an.FAULT)
    check("coolant 60C is Suspect", an.status_for(0x05, 60) == an.SUSPECT)
    check("STFT +5% Normal", an.status_for(0x06, 5) == an.NORMAL)
    check("STFT +18% Suspect", an.status_for(0x06, 18) == an.SUSPECT)
    check("STFT +30% Fault", an.status_for(0x06, 30) == an.FAULT)
    check("voltage 14.1 Normal", an.status_for(0x42, 14.1) == an.NORMAL)
    check("voltage 12.6 Fault", an.status_for(0x42, 12.6) == an.FAULT)
    check("unknown pid -> UNKNOWN", an.status_for(0x99, 5) == an.UNKNOWN)
    check("range text coolant", an.range_text(0x05) == "80–98")

    # --- snapshot health analysis ---
    healthy = {0x06: 2, 0x07: -1, 0x0C: 750, 0x0B: 33, 0x0E: 12,
               0x05: 88, 0x42: 14.0, 0x14: 0.45, 0x15: 0.6}
    findings = {f.category: f for f in an.analyze_all(healthy)}
    check("healthy fuel trim Normal", findings["Fuel Trim"].status == an.NORMAL)
    check("healthy cooling Normal", findings["Cooling System"].status == an.NORMAL)
    check("healthy charging Normal", findings["Charging System"].status == an.NORMAL)

    leaky = {**healthy, 0x06: 12, 0x07: 14, 0x0B: 55}
    lf = {f.category: f for f in an.analyze_all(leaky)}
    check("vacuum leak detected", lf["Vacuum Leak"].status == an.FAULT)
    check("lean fuel trim Fault", lf["Fuel Trim"].status == an.FAULT)

    # --- pre-purchase inspection scoring ---
    clean = an.inspection_report(
        healthy,
        {"stored": [], "pending": [], "permanent": []},
        {"MIL (check engine lamp)": "off"})
    check("clean inspection scores high", clean["score"] >= 90)
    check("clean inspection label Excellent", clean["label"] == "Excellent")

    bad = an.inspection_report(
        leaky,
        {"stored": [("P0420", "Catalyst"), ("P0301", "Misfire")],
         "pending": [], "permanent": [("P0420", "Catalyst")]},
        {"MIL (check engine lamp)": "ON"})
    check("bad inspection scores lower", bad["score"] < clean["score"])
    check("bad inspection not Excellent", bad["label"] != "Excellent")

    # --- live recorder ---
    rec = Recorder(max_points=3)
    rec.set_pids([0x0C, 0x05])
    rec.add_snapshot({0x0C: 800, 0x05: 88}, t=0.0)
    rec.add_snapshot({0x0C: 820}, t=0.5)          # coolant missing -> gap
    check("recorder length 2", len(rec) == 2)
    check("recorder latest rpm", rec.latest(0x0C) == 820)
    check("recorder gap latest coolant", rec.latest(0x05) == 88)
    t_rel, vals = rec.get(0x0C)
    check("recorder relative times", t_rel == [0.0, 0.5])
    check("recorder gap stored None", rec.get(0x05)[1] == [88, None])
    rec.add_snapshot({0x0C: 840, 0x05: 89}, t=1.0)
    rec.add_snapshot({0x0C: 860, 0x05: 90}, t=1.5)  # rolls past max_points=3
    check("recorder rolls at cap", len(rec) == 3)
    csv_text = rec.to_csv()
    check("recorder csv has header", csv_text.splitlines()[0].startswith("time_s,"))
    check("recorder csv row count", len(csv_text.strip().splitlines()) == 4)
    rec.clear()
    check("recorder clear empties", len(rec) == 0)

    # --- MAP sensor analyzer ---
    check("idle MAP 33 normal",
          an.analyze_map({0x0B: 33, 0x0C: 750}).status == an.NORMAL)
    check("idle MAP 55 suspect (weak vacuum)",
          an.analyze_map({0x0B: 55, 0x0C: 750}).status == an.SUSPECT)

    # --- fuel trim threshold moved to ±20 ---
    check("trim 18% now Suspect not Fault",
          an.analyze_fuel_trim({0x06: 9, 0x07: 9}).status == an.SUSPECT)
    check("trim 22% Fault",
          an.analyze_fuel_trim({0x06: 11, 0x07: 11}).status == an.FAULT)

    # --- analysis cards ---
    cards = cards_mod.render_all(healthy)
    titles = [c["title"] for c in cards]
    check("five analysis cards", len(cards) == 5)
    check("fuel trim card present", "Fuel Trim Analyzer" in titles)
    check("MAP card present", "MAP Sensor Analyzer" in titles)
    ft_card = next(c for c in cards if c["title"] == "Fuel Trim Analyzer")
    check("fuel trim card has causes", "Vacuum leak" in ft_card["causes"])
    check("fuel trim card has thresholds",
          any("±20%" in r for r in ft_card["reference"]))

    # --- Honda enhanced (Mode 22) read from fake ECU ---
    enh = e.read_honda_enhanced()
    enh_names = {n for n, _v, _u in enh}
    check("honda VTC angle read", "VTC cam advance angle" in enh_names)
    check("honda ATF temp read", "Transmission fluid temp" in enh_names)
    vtc = next(v for n, v, _u in enh if n == "VTC cam advance angle")
    check("honda VTC angle decodes to 30", abs(vtc - 30) < 0.1)
    hcard = cards_mod.honda_card(enh)
    check("honda card built", hcard["title"].startswith("Honda-Specific"))
    empty_card = cards_mod.honda_card([])
    check("empty honda card -> UNKNOWN", empty_card["status"] == an.UNKNOWN)

    # --- BLE characteristic selection ---
    from obdscanner import transport as tr  # noqa: E402
    vgate = [("0000fff1-0000-1000-8000-00805f9b34fb", ["notify"]),
             ("0000fff2-0000-1000-8000-00805f9b34fb", ["write-without-response"])]
    w, resp, n_uuid = tr.select_ble_uuids(vgate)
    check("BLE picks Vgate write char", w.endswith("fff2-0000-1000-8000-00805f9b34fb"))
    check("BLE picks Vgate notify char", n_uuid.endswith("fff1-0000-1000-8000-00805f9b34fb"))
    check("BLE write-without-response -> no response", resp is False)

    hm10 = [("0000ffe1-0000-1000-8000-00805f9b34fb", ["write", "notify"])]
    w2, resp2, n2 = tr.select_ble_uuids(hm10)
    check("BLE HM-10 shared char", w2 == n2 and w2.endswith("ffe1-0000-1000-8000-00805f9b34fb"))
    check("BLE plain write -> needs response", resp2 is True)

    try:
        tr.select_ble_uuids([("1234", ["read"])])
        check("BLE no usable char raises", False)
    except tr.TransportError:
        check("BLE no usable char raises", True)

    # BLE transport without bleak installed must fail with a helpful message.
    try:
        import bleak  # noqa: F401
        check("BLE bleak-missing message (skipped, bleak present)", True)
    except ImportError:
        try:
            tr.BLETransport("00:11:22:33:44:55").open()
            check("BLE missing-bleak raises", False)
        except tr.TransportError as ex:
            check("BLE missing-bleak mentions install", "bleak" in str(ex))

    # --- full data extraction: Mode 02 / 06 / 09 -----------------------
    from obdscanner import extract as ex          # noqa: E402

    vinfo = e.read_vehicle_info()
    check("Mode 09 calibration id", vinfo.get("Calibration ID") == "PNB6A100")
    check("Mode 09 CVN present", "12 34 56 78" in vinfo.get(
        "Calibration Verification (CVN)", ""))
    check("Mode 09 ECU name", vinfo.get("ECU name") == "ECM-HONDA")

    ff = e.read_freeze_frame()
    check("freeze frame DTC is P0301", ff["dtc"] == "P0301")
    check("freeze frame has RPM",
          any(name == "Engine RPM" for _p, name, _v, _u in ff["values"]))

    m06 = e.read_mode06()
    check("Mode 06 returns results", len(m06) == 2)
    o2 = next(r for r in m06 if r.mid == 0x01)
    check("Mode 06 O2 monitor PASS", o2.passed)
    cat = next(r for r in m06 if r.mid == 0x21)
    check("Mode 06 catalyst FAIL (val>max)", not cat.passed)
    check("Mode 06 catalyst named", "Catalyst" in cat.as_row()[0])

    # --- service / actuator command runner -----------------------------
    r = e.run_command("1103", 0x51)
    check("service soft-reset positive", r["ok"] and "Positive" in r["detail"])
    r = e.run_command("04", 0x44)
    check("service clear positive", r["ok"])
    # negative-response (7F) decoding
    saved = e.command
    e.command = lambda c: "7F 11 33"
    rej = e.run_command("1101", 0x51)
    check("service rejection decoded",
          (not rej["ok"]) and "security access denied" in rej["detail"])
    e.command = saved

    # --- whole-vehicle extract aggregator ------------------------------
    report = ex.full_extract(e)
    check("extract has live data", len(report["live_data"]) > 5)
    check("extract has mode06", len(report["mode06"]) == 2)
    check("extract text renders", "FULL VEHICLE EXTRACT" in ex.to_text(report))
    check("extract json renders", '"live_data"' in ex.to_json(report))

    print()
    if check.failed:
        print(f"{check.failed} test(s) FAILED")
        sys.exit(1)
    print("All tests passed.")


if __name__ == "__main__":
    main()
