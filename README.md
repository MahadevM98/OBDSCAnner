# OBD-II Scanner (ELM327, Bluetooth) — Linux GUI

A self-contained desktop app to talk to your car's ECU through an **ELM327
Bluetooth adapter**. Read live sensor data, read and **erase** trouble codes
(turn off the check-engine light), check emission-readiness monitors, read the
VIN, and send raw commands.

Built and tested with a **Honda Accord 8th gen 2.4L (K24)** in mind — the DTC
database includes the codes those cars commonly throw (P0420 catalyst, P0301-04
misfire, P0171 lean, VTEC/VTC codes, plus Honda P1xxx codes) — but it works with
any OBD-II compliant car (all cars sold in India from ~2010 onward).

## No installation needed

It uses only Python's standard library plus `pyserial`, both already on your
system. There is **nothing to `pip install`**. The ELM327 protocol is
implemented directly in `obdscanner/`.

## 1. Pair the adapter (one time)

Plug the ELM327 into the OBD-II port (under the dashboard, driver's side) and
turn the ignition to ON (engine can be off). Then pair it over Bluetooth:

```bash
bluetoothctl
# inside bluetoothctl:
power on
agent on
default-agent
scan on                # wait for a device named OBDII / OBD / V-LINK etc.
pair  AA:BB:CC:DD:EE:FF # use your adapter's MAC (PIN is usually 1234 or 0000)
trust AA:BB:CC:DD:EE:FF
scan off
exit
```

You do **not** need `sudo rfcomm bind`; the app opens an RFCOMM socket straight
to the MAC. (That older method still works if you prefer it — see below.)

The app **auto-detects the RFCOMM channel** (via `sdptool`): many adapters put
their serial port on channel 2 or 3, not 1. The number in the Channel box is
just a hint/fallback — if it's wrong, the app finds the right one anyway.

> **Most "BLE" adapters are actually dual-mode.** An adapter advertising as
> `OBDBLE` may still expose a classic Serial Port profile — in which case the
> normal **Bluetooth (RFCOMM / classic)** option is the reliable choice and the
> Bluetooth LE option is unnecessary. Try classic first.

### Bluetooth LE adapters (OBDBLE / Vgate BLE clones)

If your adapter shows up as **`OBDBLE`** (or another BLE name) and the classic
"Bluetooth (RFCOMM)" option fails with **`[Errno 113] No route to host`**, your
adapter is **Bluetooth Low Energy** — it speaks GATT, not RFCOMM. These are
sold mainly for iPhones (iOS blocks classic Bluetooth SPP). Use the
**"Bluetooth LE"** radio on the Connect tab instead.

BLE needs the `bleak` library (the one exception to "nothing to install"):

```bash
sudo apt install python3-bleak     # Debian/Ubuntu
# or:  python3 -m pip install --user bleak
bluetoothctl power on              # make sure Bluetooth is actually on
```

**Do NOT `pair` a BLE adapter in bluetoothctl.** Unlike a classic adapter, a
BLE ELM327 connects over GATT without pairing, and a stale *classic* pairing
makes BlueZ try the wrong transport — you'll see
`org.bluez.Error.BREDR.ProfileUnavailable`. If you already paired it, remove
that record first:

```bash
bluetoothctl remove AA:BB:CC:DD:EE:FF   # your adapter's MAC
```

Then: Connect tab → **Bluetooth LE** → **List paired** (the app scans for it by
MAC) → pick `OBDBLE` → **Connect**. The app discovers the device over an LE
scan and auto-detects its serial characteristics (the common FFF1/FFF2, FFE1,
and Nordic-UART profiles are built in).

## 2. Run

```bash
./run.sh
# or:
python3 obdscan.py
```

## 3. Connect in the app

1. **Connect** tab → leave "Bluetooth (RFCOMM)" selected.
2. Click **List paired** and pick your adapter (channel is usually `1`).
3. Click **Connect**. You should see the adapter version, the negotiated
   protocol (Accord 8th gen uses *ISO 15765-4 CAN 11/500*), battery voltage,
   and the VIN.

## What each tab does

| Tab | Function |
|-----|----------|
| **Connect** | Choose Bluetooth/serial, connect, show adapter + VIN + voltage |
| **Dashboard** | Live gauges (RPM, speed, coolant, MAF, throttle, fuel trims, voltage…) updating continuously. Each gauge shows the **Accord spec range** and turns **green / amber / red** by how the reading compares |
| **Trouble Codes** | Read **stored / pending / permanent** DTCs with descriptions; **ERASE** button clears codes + resets the MIL |
| **All Sensors** | One-shot snapshot of every PID your ECU supports, with a **normal range** and **status** column for the ones with a known Accord spec |
| **Live Data** | Pick any supported sensors, **record** them in real time as scrolling **strip-chart graphs** (with the spec band shaded), and **export the log to CSV**. Drawn with plain tkinter — no extra libraries |
| **Engine Health** | One-click automatic analysis of a sensor snapshot: fuel trim, vacuum-leak pattern, ignition timing, O2 sensors, catalytic converter, cooling and charging — each rated *Normal / Suspect / Fault likely* with the reasoning |
| **Analysis** | The same checks as detailed **analysis cards** — Fuel Trim, Catalytic Converter, Ignition, MAP Sensor, Cooling — each showing the reference thresholds and likely causes. Also attempts to read **Honda enhanced data** (VTEC / VTC angle / knock / transmission temp) via Mode 22 — *experimental, ECU/model dependent* |
| **Pre-Purchase** | One-click whole-vehicle scan (DTCs + readiness + key sensors) → per-section status, an **overall score** (Excellent / Good / Fair / Poor) and an **export to a text report** |
| **Readiness** | Emission monitor readiness + MIL status (useful before an emission test) |
| **Terminal** | Send raw `AT`/OBD commands (e.g. `ATRV`, `0100`, `03`) |

### Spec ranges (Honda Accord 8th gen 2.4L / K24)

`obdscanner/analysis.py` holds typical warm-engine operating ranges for this
engine (idle RPM, coolant temp, fuel trims, MAP/vacuum, charging voltage, O2
voltages, …). Live readings are flagged against these bands, and the same data
drives the **Engine Health** and **Pre-Purchase** screens. They are quick-read
guidance, **not** a replacement for the factory service manual.

### Erasing codes — read this

The **ERASE** button sends OBD **Mode 04**. It clears stored codes and
freeze-frame data and turns the check-engine light off. Best practice:

* Do it with the **engine off, ignition on**.
* If the underlying fault is still present, the code will come back after a
  drive cycle — erasing is not a repair.
* **Permanent** (Mode 0A) codes will *not* clear until the ECU re-runs its
  internal monitors and confirms the fault is gone. That's by design (anti
  emission-cheat) and is normal.

## Serial / `rfcomm bind` alternative

If you'd rather use a `/dev/rfcomm0` device (or have a USB ELM327):

```bash
sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF 1
```

Then in the **Connect** tab choose **Serial device**, port `/dev/rfcomm0`,
baud `38400` (try `9600` or `115200` for some clones).

## Offline self-test

The protocol/decoder logic is verified against an emulated ECU — no car needed:

```bash
python3 tests/test_driver.py
```

## Project layout

```
obdscan.py            launcher
obdscanner/
  transport.py        Bluetooth RFCOMM + serial transports, device listing
  elm327.py           ELM327 driver: modes 01/03/04/07/09/0A, readiness
  pids.py             Mode-01 PID table + decoders (SAE J1979 formulas)
  analysis.py         Accord spec ranges + automatic health / inspection logic
  cards.py            analysis-card definitions (thresholds + likely causes)
  honda.py            experimental Honda enhanced (Mode 22) PID table
  recorder.py         rolling time-series buffer + CSV export for live data
  chart.py            stdlib tkinter strip-chart widget (real-time graphs)
  dtc.py              DTC byte decoding + description database
  worker.py           background thread so the GUI never blocks on I/O
  gui.py              tkinter UI
tests/
  fake_elm.py         emulated Accord ECU
  test_driver.py      offline smoke test
```

## Safety / scope

This is a standard OBD-II diagnostic tool: it reads generic SAE PIDs and
DTCs and uses the standard clear-codes service. It does **not** reflash,
reprogram, or modify ECU firmware. Use it on a vehicle you own or are
authorised to service.
