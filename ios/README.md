# OBD-II Scanner — iOS app

A native SwiftUI port of the Python scanner's core: connect to a **BLE** ELM327
adapter, read live data, trouble codes, a full multi-mode extract, and send
service/reset functions.

## Why BLE only

iOS apps can talk to **Bluetooth Low Energy** ELM327 adapters through
CoreBluetooth (no extra entitlement). Classic-Bluetooth (SPP) adapters are
*not* reachable from a normal app unless the dongle is Apple MFi-certified, so
this app targets BLE adapters — e.g. Vgate iCar Pro BLE 4.0, OBDLink CX/MX+,
Veepeak BLE+. This matches the `BLETransport` path in the Python project.

## Install on iPhone WITHOUT a Mac (cloud build + sideload)

This is the no-Mac, no-paid-account route. A free macOS CI runner compiles an
**unsigned** `.ipa`; you then sign it with your **free Apple ID** and install it.
Trade-off: a free Apple ID signature **expires after 7 days** — you re-install
weekly (AltStore can auto-refresh; Sideloadly is manual).

### Step 1 — Put the code on GitHub

The cloud build runs on GitHub Actions, so the repo must be on GitHub.

```bash
cd /home/mahadev/Desktop/OBDscanner
git init && git add . && git commit -m "OBD scanner + iOS app"
# create an EMPTY repo on github.com first, then:
git remote add origin https://github.com/<you>/OBDscanner.git
git branch -M main && git push -u origin main
```

(Or `gh repo create OBDscanner --private --source=. --push` if you have the
GitHub CLI signed in.)

### Step 2 — Build the IPA in the cloud

1. On GitHub, open the **Actions** tab → enable workflows if prompted.
2. Run **"Build iOS (unsigned IPA)"** (it also runs automatically on push).
   The workflow `xcodegen generate`s the project and builds with no signing.
3. When it finishes (~5 min), open the run and download the
   **`OBDScanner-unsigned-ipa`** artifact. Unzip it to get `OBDScanner-unsigned.ipa`.

> Free GitHub minutes: public repos = unlimited; private repos get ~200 macOS
> minutes/month free, plenty for occasional builds.

### Step 3 — Sign + install with a free Apple ID

You need a computer to run the installer (it talks to the iPhone over USB).

**On Windows (easiest) — Sideloadly:**
1. Install **iTunes** (Apple's site version, not the Microsoft Store one) and
   **Sideloadly** (sideloadly.io).
2. Plug in the iPhone, trust the computer.
3. Open Sideloadly → drag in `OBDScanner-unsigned.ipa` → enter your Apple ID →
   **Start**. It fetches a free signing certificate and installs the app.

**On Linux — AltServer-Linux** (more involved):
- Use `NyaMisty/altserver-linux` with `usbmuxd` + an anisette server, or run
  Sideloadly/AltStore inside a Windows VM. Honestly, if you can borrow a Windows
  PC for 10 minutes, Step 3 is far smoother there.

**No computer at all?** You can't — the signer must install over USB the first
time. After that, AltStore can refresh over Wi-Fi if AltServer stays running.

### Step 4 — Make iOS trust the app

1. iPhone **Settings ▸ General ▸ VPN & Device Management** → tap your Apple ID →
   **Trust**.
2. iOS 16+ only: **Settings ▸ Privacy & Security ▸ Developer Mode** → turn ON →
   restart when prompted. (Without this, sideloaded apps won't launch.)
3. Open **OBD Scanner**, allow Bluetooth, and connect to your adapter.

### Free Apple ID limits (so nothing surprises you)

- App stops launching after **7 days** → re-run Sideloadly to reinstall.
- Max **3** sideloaded apps per Apple ID at once.
- Bundle id is `com.obdscanner.app` (change it in `ios/project.yml` if needed).

A paid Apple Developer account ($99/yr) removes the 7-day limit (1-year signing)
— the only "permanent" fix, if you ever want it.

---

## Building in Xcode directly (if you get Mac access)

These are plain Swift sources, not a prebuilt `.xcodeproj` (a hand-written
project file is fragile). With a Mac you can either run `xcodegen generate` (uses
`ios/project.yml`) and open the result, or create the project manually:

1. Xcode → **File ▸ New ▸ Project ▸ iOS ▸ App**.
   - Product name: `OBDScanner`
   - Interface: **SwiftUI**, Language: **Swift**
2. Delete the auto-generated `ContentView.swift` and the `…App.swift` stub.
3. Drag the `OBDScanner/` folder from here into the project navigator
   (check *Copy items if needed* and *Create groups*).
4. In the target's **Info** tab add this key (required or iOS kills the app the
   first time it touches Bluetooth):
   - `NSBluetoothAlwaysUsageDescription` →
     *"Connects to your OBD-II adapter to read vehicle data."*
   (The `xcodegen` route in `ios/project.yml` sets this for you automatically.)
5. Build to a **real iPhone** — CoreBluetooth does not work in the Simulator.

## Layout

```
OBDScanner/
  OBDScannerApp.swift     @main entry
  Models/
    BLEManager.swift      CoreBluetooth transport (scan/connect/send)
    ELM327.swift          OBD driver: PIDs, DTCs, Mode 02/06/09, services
    PIDs.swift            Mode-01 PID table + decoders (ported from pids.py)
    DTC.swift             DTC decode + description table (from dtc.py)
    Mode06.swift          On-board monitor parsing (from mode06.py)
    OBDService.swift      Service/reset catalog (from service.py)
    Extract.swift         Whole-vehicle extract report (from extract.py)
    AppModel.swift        ObservableObject tying it together
  Views/
    ContentView.swift     TabView shell
    ConnectView.swift     scan + connect, shows VIN / protocol
    DashboardView.swift   live polling gauges
    CodesView.swift       read / clear DTCs
    ExtractView.swift     run full extract, share TXT
    ServiceView.swift     reset/actuator functions + idle relearn
```

## Notes / constraints

- **Swift language mode:** written against the default **Swift 5** mode (Minimal
  strict-concurrency) that a new Xcode App template uses. The BLE layer is an
  `@MainActor` class driven off the `.main` dispatch queue, so all callbacks and
  `@Published` updates are main-thread. If you switch the target to **Swift 6**
  mode you may get concurrency warnings on the CoreBluetooth delegate
  conformance — harmless, but tell me and I'll annotate them away.
- **Real device only:** CoreBluetooth is unavailable in the iOS Simulator.
- **Source-only:** these are `.swift` files, not an `.xcodeproj`. Create the
  project per the steps above and add the files. The logic mirrors the Python
  driver one-to-one, so behaviour matches the desktop app.
- A few SF Symbols (e.g. the dashboard gauge glyph) need iOS 16+. Deployment
  target should be **iOS 16.0** or newer (uses `ShareLink`, `LabeledContent`).

## Safety

The Service tab **writes** to the car. It uses confirmation alerts and decodes
UDS negative responses (e.g. "security access denied") exactly like the Python
version. As in the desktop app, there is **no** standard command that relearns a
Honda throttle body — the documented idle-relearn *procedure* is shown instead.
