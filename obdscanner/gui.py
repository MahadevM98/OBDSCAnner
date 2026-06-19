"""
Tkinter GUI for the ELM327 OBD-II scanner.

Tabs:
  Connect          - pick Bluetooth MAC or serial port, connect, see adapter/VIN
  Dashboard        - live sensor readout that polls the ECU continuously
  Trouble Codes    - read stored/pending/permanent DTCs and ERASE them
  All Sensors      - snapshot of every supported Mode-01 PID
  Readiness        - emission monitor readiness + MIL status
  Full Extract     - one-pass dump of every reachable mode, with TXT/JSON export
  Service          - actuator / reset functions (clear, ECU reset, EVAP, relearn)
  Terminal         - send raw AT/OBD commands

All ECU I/O runs on the Worker thread; the GUI only renders results.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from . import analysis as an
from . import cards as cards_mod
from . import extract as extract_mod
from . import pids as pids_mod
from . import service as service_mod
from .chart import StripChart
from .elm327 import ELM327
from .recorder import Recorder
from .transport import (BLETransport, BluetoothTransport, SerialTransport,
                        list_paired_devices)
from .worker import Worker

POLL_MS = 60  # how often the GUI drains worker results


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OBD-II Scanner — ELM327 (Honda Accord)")
        self.root.geometry("900x620")

        self.worker = Worker()
        self.worker.start()
        self.connected = False
        self.supported_pids: list[int] = []
        self.dash_labels: dict[int, tk.Label] = {}
        self.dash_range: dict[int, tk.Label] = {}
        self.polling = False
        self.last_snapshot: dict[int, float] = {}
        self.recorder = Recorder()
        self.live_charts: dict[int, StripChart] = {}
        self.live_polling = False

        self._build_style()
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._build_connect_tab()
        self._build_dashboard_tab()
        self._build_dtc_tab()
        self._build_sensors_tab()
        self._build_livedata_tab()
        self._build_health_tab()
        self._build_analysis_tab()
        self._build_inspection_tab()
        self._build_readiness_tab()
        self._build_extract_tab()
        self._build_service_tab()
        self._build_terminal_tab()

        self.status = tk.StringVar(value="Not connected.")
        ttk.Label(root, textvariable=self.status, relief="sunken",
                  anchor="w").pack(fill="x", side="bottom")

        self.root.after(POLL_MS, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ ui
    # status -> (foreground colour, treeview row tag colour)
    STATUS_COLORS = {
        an.NORMAL: "#1a7f37",
        an.SUSPECT: "#b06a00",
        an.FAULT: "#c01c28",
        an.UNKNOWN: "#222222",
    }

    def _build_style(self):
        self.big = tkfont.Font(size=20, weight="bold")
        self.small = tkfont.Font(size=8)
        self.lbl = tkfont.Font(size=10)
        self.bold = tkfont.Font(size=11, weight="bold")
        self.mono = tkfont.Font(family="monospace", size=9)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _set_status(self, text: str):
        self.status.set(text)

    def _is_conn_lost(self, error) -> bool:
        s = str(error).lower()
        return any(k in s for k in (
            "connection lost", "not connected", "errno 107", "errno 104",
            "errno 32", "broken pipe", "transport not open"))

    def _job_error(self, error, context: str) -> None:
        """Centralised worker-error handling: a dropped Bluetooth link puts the
        UI back into a clean 'disconnected' state instead of leaving it stuck
        thinking it is still connected."""
        if self._is_conn_lost(error):
            self.connected = False
            self.polling = False
            self.live_polling = False
            try:
                self.poll_btn.configure(text="Start live data")
                self.live_btn.configure(text="Start recording")
                self.connect_btn.configure(state="normal")
                self.disconnect_btn.configure(state="disabled")
            except tk.TclError:
                pass
            self._set_status(
                "Connection lost (weak signal or the adapter dropped). Move the "
                "laptop closer / re-plug the adapter, then click Connect again.")
        else:
            self._set_status(f"{context}: {error}")

    # --------------------------------------------------------- Connect tab
    def _build_connect_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Connect")

        self.tmode = tk.StringVar(value="bt")
        modes = ttk.LabelFrame(f, text="Adapter connection")
        modes.pack(fill="x", padx=10, pady=8)

        ttk.Radiobutton(modes, text="Bluetooth (RFCOMM / classic)",
                        variable=self.tmode, value="bt",
                        command=self._refresh_conn_inputs).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(modes, text="Bluetooth LE (for OBDBLE / BLE clones)",
                        variable=self.tmode, value="ble",
                        command=self._refresh_conn_inputs).grid(
            row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(modes, text="Serial device", variable=self.tmode,
                        value="serial", command=self._refresh_conn_inputs).grid(
            row=0, column=2, sticky="w", padx=6, pady=4)

        # Bluetooth row
        self.bt_frame = ttk.Frame(modes)
        self.bt_frame.grid(row=1, column=0, columnspan=3, sticky="we", padx=6)
        ttk.Label(self.bt_frame, text="Device:").grid(row=0, column=0, sticky="w")
        self.bt_combo = ttk.Combobox(self.bt_frame, width=46)
        self.bt_combo.grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(self.bt_frame, text="List paired",
                   command=self._list_paired).grid(row=0, column=2, padx=4)
        ttk.Label(self.bt_frame, text="Channel:").grid(row=0, column=3)
        self.bt_channel = ttk.Entry(self.bt_frame, width=4)
        self.bt_channel.insert(0, "1")
        self.bt_channel.grid(row=0, column=4, padx=4)

        # Serial row
        self.serial_frame = ttk.Frame(modes)
        self.serial_frame.grid(row=2, column=0, columnspan=3, sticky="we", padx=6)
        ttk.Label(self.serial_frame, text="Port:").grid(row=0, column=0, sticky="w")
        self.serial_port = ttk.Entry(self.serial_frame, width=30)
        self.serial_port.insert(0, "/dev/rfcomm0")
        self.serial_port.grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(self.serial_frame, text="Baud:").grid(row=0, column=2)
        self.serial_baud = ttk.Combobox(
            self.serial_frame, width=8,
            values=["9600", "38400", "115200", "230400", "500000"])
        self.serial_baud.set("38400")
        self.serial_baud.grid(row=0, column=3, padx=4)

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=10, pady=6)
        self.connect_btn = ttk.Button(btns, text="Connect",
                                      command=self._connect)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(btns, text="Disconnect",
                                         command=self._disconnect,
                                         state="disabled")
        self.disconnect_btn.pack(side="left", padx=6)

        info = ttk.LabelFrame(f, text="Adapter / vehicle info")
        info.pack(fill="both", expand=True, padx=10, pady=8)
        self.info_text = tk.Text(info, height=12, wrap="word")
        self.info_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.info_text.configure(state="disabled")

        self._refresh_conn_inputs()

    def _refresh_conn_inputs(self):
        mode = self.tmode.get()
        use_bt = mode in ("bt", "ble")     # both pick a device by MAC/name
        for child in self.bt_frame.winfo_children():
            child.configure(state="normal" if use_bt else "disabled")
        # Channel only applies to classic RFCOMM, not BLE.
        if mode == "ble":
            self.bt_channel.configure(state="disabled")
        for child in self.serial_frame.winfo_children():
            try:
                child.configure(
                    state="normal" if mode == "serial" else "disabled")
            except tk.TclError:
                pass

    def _list_paired(self):
        devices = list_paired_devices()
        if not devices:
            self._set_status("No paired Bluetooth devices found "
                             "(pair the ELM327 in bluetoothctl first).")
            return
        values = [f"{mac}  {name}" for mac, name in devices]
        self.bt_combo["values"] = values
        # Prefer an OBD-looking name
        for v in values:
            if any(k in v.upper() for k in ("OBD", "ELM", "VLINK", "VGATE")):
                self.bt_combo.set(v)
                break
        else:
            self.bt_combo.set(values[0])
        self._set_status(f"Found {len(devices)} paired device(s).")

    def _info_write(self, lines: dict):
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        for k, v in lines.items():
            self.info_text.insert("end", f"{k:>18} :  {v}\n")
        self.info_text.configure(state="disabled")

    def _build_transport(self):
        mode = self.tmode.get()
        if mode in ("bt", "ble"):
            raw = self.bt_combo.get().strip()
            mac = raw.split()[0] if raw else ""
            if not mac:
                raise ValueError("Enter or pick a Bluetooth device MAC.")
            if mode == "ble":
                return BLETransport(mac)
            ch = int(self.bt_channel.get() or "1")
            return BluetoothTransport(mac, channel=ch)
        port = self.serial_port.get().strip()
        if not port:
            raise ValueError("Enter a serial port path.")
        baud = int(self.serial_baud.get() or "38400")
        return SerialTransport(port, baudrate=baud)

    def _connect(self):
        try:
            transport = self._build_transport()
        except ValueError as e:
            self._set_status(str(e))
            return
        self.connect_btn.configure(state="disabled")
        self._set_status("Connecting and negotiating protocol…")
        elm = ELM327(transport)
        self.worker.set_elm(elm)

        def job(e: ELM327):
            e.t.open()
            info = e.initialize()
            info["vin"] = e.read_vin() or "(not reported)"
            info["supported"] = sorted(e.supported_pids())
            return info

        self.worker.submit(job, self._on_connected)

    def _on_connected(self, result, error):
        if error is not None:
            self.connect_btn.configure(state="normal")
            self._set_status(f"Connection failed: {error}")
            self._info_write({"Error": str(error)})
            return
        self.connected = True
        self.supported_pids = result.get("supported", [])
        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="normal")
        self._info_write({
            "Adapter": result.get("adapter", "?"),
            "Protocol": result.get("protocol", "?"),
            "Battery voltage": result.get("voltage", "?"),
            "VIN": result.get("vin", "?"),
            "Supported PIDs": f"{len(self.supported_pids)} sensors available",
        })
        self._set_status("Connected. Live data and DTC functions are ready.")
        self._build_dash_labels()
        self._populate_live_sensors()

    def _disconnect(self):
        self.polling = False
        self.live_polling = False
        self.live_btn.configure(text="Start recording")
        self.poll_btn.configure(text="Start live data")
        self.connected = False

        def job(e: ELM327):
            if e and e.t:
                e.t.close()
            return True

        self.worker.submit(job, lambda r, err: None)
        self.connect_btn.configure(state="normal")
        self.disconnect_btn.configure(state="disabled")
        self._set_status("Disconnected.")

    # ------------------------------------------------------- Dashboard tab
    def _build_dashboard_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Dashboard")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        self.poll_btn = ttk.Button(top, text="Start live data",
                                   command=self._toggle_poll)
        self.poll_btn.pack(side="left")
        ttk.Label(top, text="  (updates continuously while connected)").pack(
            side="left")
        self.dash_grid = ttk.Frame(f)
        self.dash_grid.pack(fill="both", expand=True, padx=10, pady=6)

    def _build_dash_labels(self):
        for w in self.dash_grid.winfo_children():
            w.destroy()
        self.dash_labels.clear()
        wanted = [p for p in pids_mod.DASHBOARD_PIDS if p in self.supported_pids]
        if not wanted:  # fall back to whatever is supported
            wanted = [p for p in pids_mod.DASHBOARD_PIDS]
        cols = 4
        self.dash_range.clear()
        for i, pid in enumerate(wanted):
            name = pids_mod.PIDS.get(pid, (f"PID {pid:02X}", "", 0, None))[0]
            unit = pids_mod.PIDS.get(pid, ("", "", 0, None))[1]
            cell = ttk.LabelFrame(self.dash_grid, text=name)
            cell.grid(row=i // cols, column=i % cols, padx=6, pady=6,
                      sticky="nsew")
            lbl = tk.Label(cell, text="—", font=self.big)
            lbl.pack(padx=10, pady=(10, 0))
            rng = an.range_text(pid)
            spec_txt = f"spec {rng} {unit}".strip() if rng else "—"
            rlbl = tk.Label(cell, text=spec_txt, font=self.small,
                            foreground="#666666")
            rlbl.pack(padx=10, pady=(0, 8))
            self.dash_labels[pid] = lbl
            self.dash_range[pid] = rlbl
        for c in range(cols):
            self.dash_grid.columnconfigure(c, weight=1)

    def _toggle_poll(self):
        if not self.connected:
            self._set_status("Connect to the adapter first.")
            return
        self.polling = not self.polling
        self.poll_btn.configure(
            text="Stop live data" if self.polling else "Start live data")
        if self.polling:
            self._poll_once()

    def _poll_once(self):
        if not (self.polling and self.connected):
            return
        pids = list(self.dash_labels.keys())

        def job(e: ELM327):
            out = {}
            for pid in pids:
                r = e.query_pid(pid)
                if r is not None:
                    out[pid] = r
            return out

        self.worker.submit(job, self._on_poll)

    def _on_poll(self, result, error):
        if error is not None:
            self._job_error(error, "Live data error")
            return
        for pid, (name, value, unit) in (result or {}).items():
            lbl = self.dash_labels.get(pid)
            if lbl is not None:
                lbl.configure(text=f"{value} {unit}".strip())
                status = an.status_for(pid, value)
                lbl.configure(foreground=self.STATUS_COLORS.get(status, "#222222"))
            if isinstance(value, (int, float)):
                self.last_snapshot[pid] = value
        if self.polling and self.connected:
            self.root.after(150, self._poll_once)

    # ------------------------------------------------------ Trouble codes
    def _build_dtc_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Trouble Codes")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="Read all codes",
                   command=self._read_all_dtcs).pack(side="left")
        ttk.Button(top, text="Stored",
                   command=lambda: self._read_dtcs("stored")).pack(side="left", padx=4)
        ttk.Button(top, text="Pending",
                   command=lambda: self._read_dtcs("pending")).pack(side="left", padx=4)
        ttk.Button(top, text="Permanent",
                   command=lambda: self._read_dtcs("permanent")).pack(side="left", padx=4)
        erase = ttk.Button(top, text="⚠ ERASE codes / reset MIL",
                           command=self._erase_dtcs)
        erase.pack(side="right")

        cols = ("type", "code", "desc")
        self.dtc_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.dtc_tree.heading("type", text="Type")
        self.dtc_tree.heading("code", text="Code")
        self.dtc_tree.heading("desc", text="Description")
        self.dtc_tree.column("type", width=100, anchor="w")
        self.dtc_tree.column("code", width=80, anchor="w")
        self.dtc_tree.column("desc", width=620, anchor="w")
        self.dtc_tree.pack(fill="both", expand=True, padx=10, pady=6)

    def _require_conn(self) -> bool:
        if not self.connected:
            self._set_status("Connect to the adapter first.")
            return False
        return True

    def _read_dtcs(self, which):
        if not self._require_conn():
            return
        self._set_status(f"Reading {which} codes…")

        def job(e: ELM327):
            fn = {"stored": e.read_stored_dtcs,
                  "pending": e.read_pending_dtcs,
                  "permanent": e.read_permanent_dtcs}[which]
            return which, fn()

        self.worker.submit(job, self._on_dtcs_single)

    def _on_dtcs_single(self, result, error):
        if error is not None:
            self._job_error(error, "DTC read error")
            return
        which, codes = result
        for iid in self.dtc_tree.get_children():
            if self.dtc_tree.item(iid, "values")[0].lower() == which:
                self.dtc_tree.delete(iid)
        self._insert_dtcs(which, codes)
        self._set_status(f"{which.capitalize()}: {len(codes)} code(s).")

    def _read_all_dtcs(self):
        if not self._require_conn():
            return
        self._set_status("Reading all trouble codes…")

        def job(e: ELM327):
            return {
                "stored": e.read_stored_dtcs(),
                "pending": e.read_pending_dtcs(),
                "permanent": e.read_permanent_dtcs(),
            }

        self.worker.submit(job, self._on_dtcs_all)

    def _on_dtcs_all(self, result, error):
        if error is not None:
            self._job_error(error, "DTC read error")
            return
        self.dtc_tree.delete(*self.dtc_tree.get_children())
        total = 0
        for which in ("stored", "pending", "permanent"):
            codes = result.get(which, [])
            total += len(codes)
            self._insert_dtcs(which, codes)
        if total == 0:
            self.dtc_tree.insert("", "end",
                                 values=("—", "", "No trouble codes. ✔"))
        self._set_status(f"Done. {total} trouble code(s) total.")

    def _insert_dtcs(self, which, codes):
        for code, desc in codes:
            self.dtc_tree.insert("", "end", values=(which, code, desc))

    def _erase_dtcs(self):
        if not self._require_conn():
            return
        ok = messagebox.askyesno(
            "Erase trouble codes",
            "This sends OBD Mode 04: it clears stored DTCs and freeze-frame "
            "data and turns off the check-engine light.\n\n"
            "Do this with the engine OFF and ignition ON. Permanent (Mode 0A) "
            "codes will only clear after the ECU re-runs its monitors.\n\n"
            "Proceed?")
        if not ok:
            return
        self._set_status("Erasing trouble codes…")

        def job(e: ELM327):
            return e.clear_dtcs()

        self.worker.submit(job, self._on_erased)

    def _on_erased(self, result, error):
        if error is not None:
            self._job_error(error, "Erase error")
            return
        if result:
            self.dtc_tree.delete(*self.dtc_tree.get_children())
            self._set_status("Codes erased and MIL reset. Re-read to confirm.")
        else:
            self._set_status("Erase command sent but ECU did not confirm.")

    # ---------------------------------------------------------- Sensors tab
    def _build_sensors_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="All Sensors")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="Read all supported sensors",
                   command=self._read_all_sensors).pack(side="left")
        ttk.Label(top, text="  (Accord spec range + status shown where known)"
                  ).pack(side="left")
        cols = ("sensor", "value", "unit", "range", "status")
        self.sensor_tree = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in (("sensor", 300), ("value", 110), ("unit", 70),
                     ("range", 140), ("status", 110)):
            self.sensor_tree.heading(c, text=c.capitalize())
            self.sensor_tree.column(c, width=w, anchor="w")
        for status, color in self.STATUS_COLORS.items():
            self.sensor_tree.tag_configure(status, foreground=color)
        self.sensor_tree.pack(fill="both", expand=True, padx=10, pady=6)

    def _read_all_sensors(self):
        if not self._require_conn():
            return
        self._set_status("Reading all supported sensors…")
        pids = list(self.supported_pids)

        def job(e: ELM327):
            rows = []
            for pid in pids:
                if pid not in pids_mod.PIDS:
                    continue
                r = e.query_pid(pid)
                if r is not None:
                    rows.append((pid,) + tuple(r))
            return rows

        self.worker.submit(job, self._on_sensors)

    def _on_sensors(self, result, error):
        if error is not None:
            self._job_error(error, "Sensor read error")
            return
        self.sensor_tree.delete(*self.sensor_tree.get_children())
        for pid, name, value, unit in (result or []):
            status = an.status_for(pid, value)
            rng = an.range_text(pid)
            self.sensor_tree.insert(
                "", "end", values=(name, value, unit, rng, status),
                tags=(status,))
            if isinstance(value, (int, float)):
                self.last_snapshot[pid] = value
        self._set_status(f"Read {len(result or [])} sensor(s).")

    # --------------------------------------------------------- Live Data tab
    # Sensors offered by default for live graphing (filtered to supported).
    LIVE_DEFAULT = [0x0C, 0x0D, 0x05, 0x0B, 0x06, 0x07, 0x0E, 0x14]

    def _build_livedata_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Live Data")

        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        self.live_btn = ttk.Button(top, text="Start recording",
                                   command=self._toggle_live)
        self.live_btn.pack(side="left")
        ttk.Button(top, text="Apply sensor selection",
                   command=self._apply_live_sensors).pack(side="left", padx=6)
        ttk.Button(top, text="Clear", command=self._clear_live).pack(side="left")
        ttk.Button(top, text="Export CSV…",
                   command=self._export_csv).pack(side="left", padx=6)
        self.live_count = tk.StringVar(value="0 samples")
        ttk.Label(top, textvariable=self.live_count).pack(side="right")

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, padx=10, pady=4)

        # Left: sensor picker.
        left = ttk.LabelFrame(body, text="Sensors to record")
        left.pack(side="left", fill="y")
        self.live_list = tk.Listbox(left, selectmode="extended",
                                    width=26, height=22, exportselection=False)
        self.live_list.pack(side="left", fill="y", padx=4, pady=4)
        lsb = ttk.Scrollbar(left, orient="vertical",
                            command=self.live_list.yview)
        lsb.pack(side="right", fill="y")
        self.live_list.configure(yscrollcommand=lsb.set)
        self.live_list_pids: list[int] = []

        # Right: scrollable column of charts.
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.live_chart_area = self._scrollable(right)

    def _scrollable(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return inner

    def _populate_live_sensors(self):
        self.live_list.delete(0, "end")
        # Start from what the ECU advertises, but always offer the curated
        # default sensors too: many ECUs (Honda included) under-report their
        # Mode-01 support bitmap yet still answer those PIDs — e.g. LTFT (0x07)
        # is frequently omitted from the bitmap despite responding. Without
        # this, such sensors never appear in the picker.
        self.live_list_pids = [p for p in self.supported_pids
                               if p in pids_mod.PIDS] or list(pids_mod.PIDS)
        for p in self.LIVE_DEFAULT:
            if p in pids_mod.PIDS and p not in self.live_list_pids:
                self.live_list_pids.append(p)
        for pid in self.live_list_pids:
            name, unit = pids_mod.PIDS[pid][:2]
            self.live_list.insert("end", f"{name} ({unit})" if unit else name)
        for i, pid in enumerate(self.live_list_pids):
            if pid in self.LIVE_DEFAULT:
                self.live_list.selection_set(i)
        self._apply_live_sensors()

    def _selected_live_pids(self) -> list[int]:
        return [self.live_list_pids[i] for i in self.live_list.curselection()]

    def _apply_live_sensors(self):
        pids = self._selected_live_pids()
        for w in self.live_chart_area.winfo_children():
            w.destroy()
        self.live_charts.clear()
        for pid in pids:
            name, unit = pids_mod.PIDS.get(pid, ("?", ""))[:2]
            spec = an.SPECS.get(pid)
            band = (spec.normal_lo, spec.normal_hi) if spec else None
            chart = StripChart(self.live_chart_area, title=name, unit=unit,
                               spec=band)
            chart.pack(fill="x", pady=4)
            self.live_charts[pid] = chart
        self.recorder.set_pids(pids)
        self._refresh_live_charts()
        self._set_status(f"Live graph: tracking {len(pids)} sensor(s).")

    def _toggle_live(self):
        if not self.connected:
            self._set_status("Connect to the adapter first.")
            return
        if not self.live_charts:
            self._set_status("Select at least one sensor, then Apply.")
            return
        self.live_polling = not self.live_polling
        self.live_btn.configure(
            text="Stop recording" if self.live_polling else "Start recording")
        if self.live_polling:
            self._live_poll_once()

    def _live_poll_once(self):
        if not (self.live_polling and self.connected):
            return
        pids = list(self.live_charts.keys())

        def job(e: ELM327):
            out = {}
            for pid in pids:
                r = e.query_pid(pid)
                if r is not None and isinstance(r[1], (int, float)):
                    out[pid] = r[1]
            return out

        self.worker.submit(job, self._on_live_poll)

    def _on_live_poll(self, result, error):
        if error is not None:
            self._job_error(error, "Live data error")
            return
        self.recorder.add_snapshot(result or {})
        self.last_snapshot.update(result or {})
        self._refresh_live_charts()
        if self.live_polling and self.connected:
            self.root.after(250, self._live_poll_once)

    def _refresh_live_charts(self):
        for pid, chart in self.live_charts.items():
            times, values = self.recorder.get(pid)
            chart.redraw(times, values)
        self.live_count.set(f"{len(self.recorder)} samples")

    def _clear_live(self):
        self.recorder.clear()
        self._refresh_live_charts()
        self._set_status("Live recording cleared.")

    def _export_csv(self):
        if len(self.recorder) == 0:
            self._set_status("Nothing recorded yet.")
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Export recorded data",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.recorder.to_csv())
            self._set_status(f"Exported {len(self.recorder)} samples to {path}")
        except OSError as e:
            self._set_status(f"Could not export: {e}")

    # ----------------------------------------------------- Engine Health tab
    def _build_health_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Engine Health")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="Run health analysis",
                   command=self._run_health).pack(side="left")
        ttk.Label(top, text="  (reads a sensor snapshot and interprets it — "
                            "engine running, warm)").pack(side="left")
        cols = ("category", "status", "detail")
        self.health_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.health_tree.heading("category", text="System")
        self.health_tree.heading("status", text="Status")
        self.health_tree.heading("detail", text="Finding")
        self.health_tree.column("category", width=160, anchor="w")
        self.health_tree.column("status", width=100, anchor="w")
        self.health_tree.column("detail", width=540, anchor="w")
        for status, color in self.STATUS_COLORS.items():
            self.health_tree.tag_configure(status, foreground=color)
        self.health_tree.pack(fill="both", expand=True, padx=10, pady=6)

    def _run_health(self):
        if not self._require_conn():
            return
        self._set_status("Reading sensor snapshot for health analysis…")
        pids = sorted(set(an.SPECS) & set(self.supported_pids)) or list(an.SPECS)

        def job(e: ELM327):
            snap = {}
            for pid in pids:
                r = e.query_pid(pid)
                if r is not None and isinstance(r[1], (int, float)):
                    snap[pid] = r[1]
            return snap

        self.worker.submit(job, self._on_health)

    def _on_health(self, result, error):
        if error is not None:
            self._job_error(error, "Health analysis error")
            return
        self.last_snapshot.update(result or {})
        self.health_tree.delete(*self.health_tree.get_children())
        findings = an.analyze_all(result or {})
        for fnd in findings:
            self.health_tree.insert(
                "", "end", values=(fnd.category, fnd.status, fnd.detail),
                tags=(fnd.status,))
        overall = an.worst(*[f.status for f in findings])
        self._set_status(f"Health analysis done. Overall: {overall}.")

    # ----------------------------------------------------- Analysis cards tab
    def _build_analysis_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Analysis")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="Run analysis cards",
                   command=self._run_cards).pack(side="left")
        ttk.Label(top, text="  (reads a live snapshot + tries Honda enhanced "
                            "data — engine running, warm)").pack(side="left")
        self.cards_area = self._scrollable(f)

    def _run_cards(self):
        if not self._require_conn():
            return
        self._set_status("Reading snapshot for analysis cards…")
        pids = sorted(set(an.SPECS) & set(self.supported_pids)) or list(an.SPECS)

        def job(e: ELM327):
            snap = {}
            for pid in pids:
                r = e.query_pid(pid)
                if r is not None and isinstance(r[1], (int, float)):
                    snap[pid] = r[1]
            enhanced = e.read_honda_enhanced()
            return snap, enhanced

        self.worker.submit(job, self._on_cards)

    def _on_cards(self, result, error):
        if error is not None:
            self._job_error(error, "Analysis error")
            return
        snap, enhanced = result
        self.last_snapshot.update(snap)
        for w in self.cards_area.winfo_children():
            w.destroy()
        rendered = cards_mod.render_all(snap)
        rendered.append(cards_mod.honda_card(enhanced))
        worst = an.UNKNOWN
        for card in rendered:
            self._render_card_widget(card)
            worst = an.worst(worst, card["status"])
        self._set_status(f"Analysis cards updated. Worst status: {worst}.")

    def _render_card_widget(self, card: dict):
        color = self.STATUS_COLORS.get(card["status"], "#222222")
        frame = ttk.LabelFrame(self.cards_area, text=card["title"])
        frame.pack(fill="x", expand=True, padx=4, pady=5)
        head = tk.Label(frame, text=f"{card['status']}", font=self.lbl,
                        foreground=color)
        head.pack(anchor="w", padx=8, pady=(4, 0))
        tk.Label(frame, text=card["detail"], wraplength=720, justify="left"
                 ).pack(anchor="w", padx=8, pady=(0, 4))
        ref = card.get("reference") or []
        if ref:
            tk.Label(frame, text="\n".join(ref), font=self.small,
                     foreground="#555555", justify="left").pack(
                anchor="w", padx=14)
        causes = card.get("causes") or []
        if causes and card["status"] != an.NORMAL:
            tk.Label(frame, text="Possible causes: " + ", ".join(causes),
                     font=self.small, foreground="#80502a",
                     wraplength=720, justify="left").pack(
                anchor="w", padx=8, pady=(2, 4))

    # ------------------------------------------------ Pre-Purchase Inspection
    def _build_inspection_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Pre-Purchase")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="One-click vehicle scan",
                   command=self._run_inspection).pack(side="left")
        self.insp_export_btn = ttk.Button(top, text="Export report…",
                                          command=self._export_inspection,
                                          state="disabled")
        self.insp_export_btn.pack(side="left", padx=6)

        self.insp_score = tk.Label(f, text="Run a scan to score the vehicle.",
                                   font=self.big)
        self.insp_score.pack(anchor="w", padx=12, pady=4)

        cols = ("section", "status", "detail")
        self.insp_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.insp_tree.heading("section", text="Section")
        self.insp_tree.heading("status", text="Status")
        self.insp_tree.heading("detail", text="Finding")
        self.insp_tree.column("section", width=170, anchor="w")
        self.insp_tree.column("status", width=100, anchor="w")
        self.insp_tree.column("detail", width=530, anchor="w")
        for status, color in self.STATUS_COLORS.items():
            self.insp_tree.tag_configure(status, foreground=color)
        self.insp_tree.pack(fill="both", expand=True, padx=10, pady=6)
        self.last_inspection: dict | None = None

    def _run_inspection(self):
        if not self._require_conn():
            return
        self._set_status("Running full vehicle scan (DTCs, monitors, sensors)…")
        pids = sorted(set(an.SPECS) & set(self.supported_pids)) or list(an.SPECS)

        def job(e: ELM327):
            snap = {}
            for pid in pids:
                r = e.query_pid(pid)
                if r is not None and isinstance(r[1], (int, float)):
                    snap[pid] = r[1]
            dtcs = {
                "stored": e.read_stored_dtcs(),
                "pending": e.read_pending_dtcs(),
                "permanent": e.read_permanent_dtcs(),
            }
            monitors = e.read_monitors()
            return snap, dtcs, monitors

        self.worker.submit(job, self._on_inspection)

    def _on_inspection(self, result, error):
        if error is not None:
            self._job_error(error, "Inspection error")
            return
        snap, dtcs, monitors = result
        self.last_snapshot.update(snap)
        report = an.inspection_report(snap, dtcs, monitors)
        report["dtcs"] = dtcs
        report["monitors"] = monitors
        self.last_inspection = report
        self.insp_tree.delete(*self.insp_tree.get_children())
        for name, status, detail in report["sections"]:
            self.insp_tree.insert("", "end", values=(name, status, detail),
                                  tags=(status,))
        self.insp_score.configure(
            text=f"Overall: {report['label']}  ({report['score']}/100)   "
                 f"· {report['dtc_total']} trouble code(s)")
        self.insp_export_btn.configure(state="normal")
        self._set_status(f"Vehicle scan complete: {report['label']}.")

    def _export_inspection(self):
        if not self.last_inspection:
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Save inspection report",
            defaultextension=".txt",
            filetypes=[("Text report", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._inspection_text(self.last_inspection))
            self._set_status(f"Report saved to {path}")
        except OSError as e:
            self._set_status(f"Could not save report: {e}")

    def _inspection_text(self, report: dict) -> str:
        import datetime
        lines = [
            "Honda Accord 8th gen 2.4L — Pre-Purchase Inspection Report",
            "=" * 58,
            f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M}",
            "",
            f"Overall rating : {report['label']}  ({report['score']}/100)",
            f"Trouble codes  : {report['dtc_total']}",
            "",
            "Section results",
            "-" * 58,
        ]
        for name, status, detail in report["sections"]:
            lines.append(f"  {name:<22} {status:<13} {detail}")
        lines += ["", "Trouble codes", "-" * 58]
        dtcs = report.get("dtcs", {})
        any_code = False
        for kind in ("stored", "pending", "permanent"):
            for code, desc in dtcs.get(kind, []):
                any_code = True
                lines.append(f"  [{kind:<9}] {code}  {desc}")
        if not any_code:
            lines.append("  None.")
        lines += ["", "Emission monitors", "-" * 58]
        for k, v in report.get("monitors", {}).items():
            lines.append(f"  {k:<28} {v}")
        lines += ["", "Note: automated guidance for a quick assessment, not a "
                  "substitute for a", "professional inspection or the factory "
                  "service manual.", ""]
        return "\n".join(lines)

    # -------------------------------------------------------- Readiness tab
    def _build_readiness_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Readiness")
        ttk.Button(f, text="Read emission monitors",
                   command=self._read_monitors).pack(anchor="w", padx=10, pady=6)
        cols = ("monitor", "status")
        self.mon_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.mon_tree.heading("monitor", text="Monitor")
        self.mon_tree.heading("status", text="Status")
        self.mon_tree.column("monitor", width=420, anchor="w")
        self.mon_tree.column("status", width=160, anchor="w")
        self.mon_tree.pack(fill="both", expand=True, padx=10, pady=6)

    def _read_monitors(self):
        if not self._require_conn():
            return
        self._set_status("Reading readiness monitors…")
        self.worker.submit(lambda e: e.read_monitors(), self._on_monitors)

    def _on_monitors(self, result, error):
        if error is not None:
            self._job_error(error, "Monitor read error")
            return
        self.mon_tree.delete(*self.mon_tree.get_children())
        for k, v in (result or {}).items():
            self.mon_tree.insert("", "end", values=(k, v))
        self._set_status("Readiness monitors updated.")

    # ------------------------------------------------------ Full Extract tab
    def _build_extract_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Full Extract")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Button(top, text="Extract everything",
                   command=self._run_full_extract).pack(side="left")
        self.export_txt_btn = ttk.Button(top, text="Export TXT…",
                                         command=lambda: self._export_report("txt"),
                                         state="disabled")
        self.export_txt_btn.pack(side="left", padx=6)
        self.export_json_btn = ttk.Button(top, text="Export JSON…",
                                          command=lambda: self._export_report("json"),
                                          state="disabled")
        self.export_json_btn.pack(side="left")
        ttk.Label(top, text="  Reads every mode the adapter can reach "
                  "(01/02/03/06/07/09/0A/22)").pack(side="left")
        self.extract_out = tk.Text(f, wrap="none", font=self.mono,
                                   background="#101418", foreground="#cfe8ff")
        self.extract_out.pack(fill="both", expand=True, padx=10, pady=6)
        self._last_report = None

    def _run_full_extract(self):
        if not self._require_conn():
            return
        self._set_status("Extracting all data… this can take 15–30 s.")
        self.extract_out.delete("1.0", "end")
        self.extract_out.insert("end", "Working… reading every supported "
                                "mode. Please wait.\n")

        def job(e: ELM327):
            return extract_mod.full_extract(e)

        self.worker.submit(job, self._on_full_extract)

    def _on_full_extract(self, result, error):
        if error is not None:
            self._job_error(error, "Extract error")
            return
        self._last_report = result
        self.extract_out.delete("1.0", "end")
        self.extract_out.insert("end", extract_mod.to_text(result))
        self.export_txt_btn.configure(state="normal")
        self.export_json_btn.configure(state="normal")
        self._set_status("Full extract complete.")

    def _export_report(self, kind: str):
        if not self._last_report:
            self._set_status("Run an extract first.")
            return
        if kind == "json":
            data = extract_mod.to_json(self._last_report)
            ext, types = ".json", [("JSON", "*.json")]
        else:
            data = extract_mod.to_text(self._last_report)
            ext, types = ".txt", [("Text", "*.txt")]
        path = filedialog.asksaveasfilename(
            defaultextension=ext, filetypes=types,
            initialfile=f"obd_extract{ext}")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data)
            self._set_status(f"Saved {path}")
        except OSError as e:
            self._set_status(f"Save failed: {e}")

    # ---------------------------------------------------------- Service tab
    def _build_service_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Service")

        warn = ("These functions WRITE to the car. Only run them with the "
                "vehicle safely parked. The ECU may reject UDS/actuator "
                "requests — that is normal and harmless.")
        ttk.Label(f, text=warn, wraplength=850, foreground="#a05000").pack(
            fill="x", padx=10, pady=(8, 4))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, padx=10, pady=4)

        left = ttk.LabelFrame(body, text="Functions")
        left.pack(side="left", fill="y")
        for spec in service_mod.COMMANDS:
            row = ttk.Frame(left)
            row.pack(fill="x", padx=6, pady=3)
            tag = "⚠ " if spec["risk"] == "caution" else "✓ "
            ttk.Button(row, text=tag + spec["title"], width=42,
                       command=lambda s=spec: self._run_service(s)).pack(
                side="left")
            ttk.Label(row, text=spec["engine"], foreground="#666666").pack(
                side="left", padx=6)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(right, text="Honda idle / throttle relearn",
                  font=self.bold).pack(anchor="w")
        proc = tk.Text(right, wrap="word", height=20, font=self.small,
                       background="#f7f7f4")
        proc.pack(fill="both", expand=True, pady=4)
        proc.insert("end", service_mod.IDLE_RELEARN_PROCEDURE)
        proc.configure(state="disabled")

        self.service_out = tk.Text(f, height=8, wrap="word",
                                   background="#101418", foreground="#9fef9f")
        self.service_out.pack(fill="x", padx=10, pady=(0, 8))

    def _run_service(self, spec: dict):
        if not self._require_conn():
            return
        msg = f"{spec['title']}\n\n{spec['detail']}\n\nEngine state: " \
              f"{spec['engine']}\n\nProceed?"
        if spec["risk"] == "caution":
            msg += "\n\n(This writes to the ECU.)"
        if not messagebox.askyesno("Confirm service function", msg):
            return
        self.service_out.insert("end", f">>> {spec['title']}\n")
        self.service_out.see("end")
        steps, expect = spec["steps"], spec["expect"]

        def job(e: ELM327):
            last = None
            for cmd in steps:
                last = e.run_command(cmd, expect if cmd is steps[-1] else None)
                if not last["ok"] and "rejected" in last["detail"]:
                    break
            return last

        self.worker.submit(job, self._on_service)

    def _on_service(self, result, error):
        if error is not None:
            self._job_error(error, "Service error")
            return
        r = result or {}
        mark = "OK" if r.get("ok") else "—"
        self.service_out.insert(
            "end", f"  [{mark}] {r.get('detail', '?')}\n"
                   f"      raw: {r.get('raw', '')}\n\n")
        self.service_out.see("end")
        self._set_status("Service function complete.")

    # --------------------------------------------------------- Terminal tab
    def _build_terminal_tab(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Terminal")
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Label(top, text="Command:").pack(side="left")
        self.term_entry = ttk.Entry(top, width=30)
        self.term_entry.pack(side="left", padx=4)
        self.term_entry.bind("<Return>", lambda _e: self._send_raw())
        ttk.Button(top, text="Send", command=self._send_raw).pack(side="left")
        for label, cmd in (("ATI", "ATI"), ("ATRV", "ATRV"),
                           ("0100", "0100"), ("03", "03")):
            ttk.Button(top, text=label,
                       command=lambda c=cmd: self._send_raw(c)).pack(
                side="left", padx=2)
        self.term_out = tk.Text(f, height=20, wrap="word",
                                background="#101418", foreground="#9fef9f")
        self.term_out.pack(fill="both", expand=True, padx=10, pady=6)

    def _send_raw(self, preset=None):
        if not self._require_conn():
            return
        cmd = (preset or self.term_entry.get()).strip()
        if not cmd:
            return
        self.term_out.insert("end", f">>> {cmd}\n")
        self.term_out.see("end")

        def job(e: ELM327):
            return e.command(cmd)

        self.worker.submit(job, self._on_raw)

    def _on_raw(self, result, error):
        if error is not None:
            self.term_out.insert("end", f"!! {error}\n\n")
        else:
            self.term_out.insert("end", f"{result}\n\n")
        self.term_out.see("end")

    # ---------------------------------------------------------------- loop
    def _pump(self):
        self.worker.poll_results()
        self.root.after(POLL_MS, self._pump)

    def _on_close(self):
        self.polling = False
        self.live_polling = False
        try:
            if self.worker.elm and self.worker.elm.t:
                self.worker.elm.t.close()
        except Exception:
            pass
        self.worker.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
