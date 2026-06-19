"""
Minimal ELM327 driver implementing the OBD-II services this app uses:

  Mode 01  current data            -> live sensors / dashboard
  Mode 02  freeze frame            -> snapshot stored when a DTC set
  Mode 03  stored DTCs             -> trouble codes (MIL on)
  Mode 04  clear DTCs              -> ERASE codes + turn off MIL
  Mode 06  on-board monitor tests  -> catalyst/O2/EVAP test results + limits
  Mode 07  pending DTCs            -> codes from current/last drive cycle
  Mode 09  vehicle info            -> VIN, calibration id, CVN, ECU name
  Mode 0A  permanent DTCs          -> codes the ECU won't let you clear yet
  Mode 22  Honda enhanced          -> experimental manufacturer parameters
  Mode 01 PID 01 -> readiness monitor status
  Plus run_command() for UDS/actuator service functions (see service.py).

The driver is synchronous and intended to be driven from a single worker
thread (see worker.py). It talks to a Transport (Bluetooth or serial).
"""

from __future__ import annotations

import time

from . import dtc as dtc_mod
from . import honda as honda_mod
from . import mode06 as mode06_mod
from . import pids as pids_mod
from .transport import TransportError

PROMPT = b">"


class ELM327Error(Exception):
    pass


class ELM327:
    def __init__(self, transport, read_timeout: float = 8.0):
        self.t = transport
        self.read_timeout = read_timeout
        self.adapter_id = ""
        self.protocol = ""

    # --- low level I/O ----------------------------------------------------
    def _send_raw(self, command: str) -> str:
        self.t.write((command + "\r").encode("ascii"))
        return self._read_until_prompt()

    def _read_until_prompt(self) -> str:
        buf = bytearray()
        deadline = time.time() + self.read_timeout
        while time.time() < deadline:
            chunk = self.t.read(256)
            if chunk:
                buf.extend(chunk)
                if PROMPT in buf:
                    break
            else:
                # brief idle; keep waiting until timeout
                time.sleep(0.01)
        text = buf.decode("ascii", errors="ignore")
        return text.replace(">", "").strip()

    def command(self, command: str) -> str:
        """Send a command, return the cleaned text response (echo removed)."""
        raw = self._send_raw(command)
        lines = []
        for line in raw.replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            # drop the echoed command itself
            if line.upper().replace(" ", "") == command.upper().replace(" ", ""):
                continue
            lines.append(line)
        return "\n".join(lines)

    # --- session setup ----------------------------------------------------
    def initialize(self) -> dict:
        """Reset the adapter and configure it for automatic protocol search."""
        info = {}
        self.command("ATZ")          # full reset
        time.sleep(0.4)
        self.command("ATE0")         # echo off
        self.command("ATL0")         # linefeeds off
        self.command("ATS0")         # spaces off
        self.command("ATH0")         # headers off (simpler parsing)
        self.command("ATSP0")        # auto protocol
        try:
            self.adapter_id = self.command("ATI") or self.command("AT@1")
        except TransportError:
            self.adapter_id = ""
        info["adapter"] = self.adapter_id
        # Wake the OBD link so a protocol gets negotiated.
        self.command("0100")
        info["protocol"] = self.describe_protocol()
        info["voltage"] = self.read_voltage()
        return info

    def describe_protocol(self) -> str:
        resp = self.command("ATDPN")  # protocol number
        name = self.command("ATDP")   # protocol name
        self.protocol = f"{name} ({resp})".strip()
        return self.protocol

    def read_voltage(self) -> str:
        v = self.command("ATRV")
        return v.strip()

    # --- helpers to parse OBD hex responses ------------------------------
    @staticmethod
    def _hex_bytes(line: str) -> list[int]:
        line = line.replace(" ", "")
        out = []
        for i in range(0, len(line) - 1, 2):
            try:
                out.append(int(line[i:i + 2], 16))
            except ValueError:
                return []
        return out

    @staticmethod
    def _is_error(resp: str) -> bool:
        bad = ("NO DATA", "ERROR", "UNABLE TO CONNECT", "BUS INIT",
               "CAN ERROR", "STOPPED", "?", "SEARCHING")
        up = resp.upper()
        return (not resp) or any(b in up for b in bad if b != "SEARCHING") or up == "SEARCHING"

    # --- Mode 01: current data -------------------------------------------
    def query_pid(self, pid: int):
        """Return (name, value, unit) for a Mode-01 PID, or None."""
        resp = self.command(f"01{pid:02X}")
        if self._is_error(resp):
            return None
        for line in resp.split("\n"):
            b = self._hex_bytes(line)
            # Expect: 41 <pid> <data...>
            if len(b) >= 2 and b[0] == 0x41 and b[1] == pid:
                return pids_mod.decode(pid, b[2:])
        return None

    def supported_pids(self) -> set[int]:
        """Walk the 0x00/0x20/0x40/0x60/0x80 support bitmaps."""
        found: set[int] = set()
        for base in (0x00, 0x20, 0x40, 0x60, 0x80):
            resp = self.command(f"01{base:02X}")
            if self._is_error(resp):
                break
            bitmap = None
            for line in resp.split("\n"):
                b = self._hex_bytes(line)
                if len(b) >= 6 and b[0] == 0x41 and b[1] == base:
                    bitmap = b[2:6]
                    break
            if bitmap is None:
                break
            value = (bitmap[0] << 24) | (bitmap[1] << 16) | (bitmap[2] << 8) | bitmap[3]
            for i in range(32):
                if value & (1 << (31 - i)):
                    found.add(base + i + 1)
            # If the "next block supported" bit (last PID of block) is clear, stop.
            if not (value & 0x1):
                break
        found.discard(0x20)
        found.discard(0x40)
        found.discard(0x60)
        found.discard(0x80)
        return found

    # --- Mode 03 / 07 / 0A: trouble codes --------------------------------
    def _read_dtcs(self, mode_hex: str, response_prefix: int) -> list[tuple[str, str]]:
        resp = self.command(mode_hex)
        if self._is_error(resp):
            return []

        # Flatten every line into one byte stream, dropping ISO-TP frame
        # counters ("0:", "1:" ...) that ELM327 prints for multi-frame CAN
        # replies. The leading length header (e.g. "0007") lands before the
        # mode-response byte and is discarded when we slice at that byte.
        tokens: list[str] = []
        for line in resp.split("\n"):
            for tok in line.split():
                if tok.endswith(":"):  # frame counter
                    continue
                tokens.append(tok)
        data = self._hex_bytes("".join(tokens))
        if response_prefix in data:
            payload = data[data.index(response_prefix) + 1:]
        else:
            payload = data

        # On CAN, the response carries a DTC-count byte before the codes,
        # which makes the remaining length odd; legacy protocols omit it
        # (even length). Parity tells the two apart reliably.
        if len(payload) % 2 == 1:
            payload = payload[1:]

        codes: list[tuple[str, str]] = []
        seen = set()
        for i in range(0, len(payload) - 1, 2):
            code = dtc_mod.decode_dtc(payload[i], payload[i + 1])
            if code and code not in seen:
                seen.add(code)
                codes.append((code, dtc_mod.describe(code)))
        return codes

    def read_stored_dtcs(self):
        return self._read_dtcs("03", 0x43)

    def read_pending_dtcs(self):
        return self._read_dtcs("07", 0x47)

    def read_permanent_dtcs(self):
        return self._read_dtcs("0A", 0x4A)

    # --- Mode 04: clear / erase ------------------------------------------
    def clear_dtcs(self) -> bool:
        """Erase stored DTCs and freeze-frame data, turn off the MIL."""
        resp = self.command("04")
        up = resp.upper()
        if "44" in up.replace(" ", ""):
            return True
        # Some adapters return just "OK" or an empty positive response.
        return not self._is_error(resp)

    # --- Mode 09: VIN -----------------------------------------------------
    def read_vin(self) -> str:
        resp = self.command("0902")
        if self._is_error(resp):
            return ""
        hex_payload = []
        for line in resp.split("\n"):
            b = self._hex_bytes(line)
            if not b:
                continue
            # Lines look like "49 02 01 <ascii...>" possibly with frame counters.
            try:
                idx = b.index(0x49)
                seg = b[idx + 3:]  # skip 49 02 <msgcount>
            except ValueError:
                seg = b
            hex_payload.extend(seg)
        chars = [chr(c) for c in hex_payload if 32 <= c <= 126]
        vin = "".join(chars).strip()
        # VINs are 17 chars; trim padding
        return vin[-17:] if len(vin) >= 17 else vin

    # --- Mode 22: Honda enhanced (experimental) --------------------------
    def query_enhanced(self, pid16: int):
        """Query one Mode-22 (2-byte) PID. Returns the data bytes after the
        '62 <hi> <lo>' header, or None if the ECU did not answer it."""
        resp = self.command(f"22{pid16:04X}")
        if self._is_error(resp):
            return None
        hi, lo = (pid16 >> 8) & 0xFF, pid16 & 0xFF
        for line in resp.split("\n"):
            b = self._hex_bytes(line)
            if len(b) >= 3 and b[0] == 0x62 and b[1] == hi and b[2] == lo:
                return b[3:]
        return None

    def read_honda_enhanced(self) -> list[tuple]:
        """Best-effort read of Honda enhanced parameters. Returns a list of
        (name, value, unit); empty if none are supported (the common case)."""
        out = []
        for pid, (name, unit, n, fn) in honda_mod.ENHANCED.items():
            data = self.query_enhanced(pid)
            if data is None or len(data) < n:
                continue
            try:
                value = fn(data)
            except Exception:
                continue
            out.append((name, value, unit))
        return out

    # --- Mode 02: freeze frame -------------------------------------------
    def read_freeze_frame(self, pids=None) -> dict:
        """Read the freeze-frame snapshot the ECU stored when a DTC set.

        Returns {"dtc": <code or "">, "values": [(pid, name, value, unit), ...]}.
        Mode 02 mirrors Mode 01 but the response is '42 <pid> <frame> <data>',
        so we decode the data with the same PID table after skipping the frame
        byte. Frame 0 is the standard stored frame.
        """
        out = {"dtc": "", "values": []}
        # PID 02 in frame 0 = the DTC that triggered the freeze frame.
        resp = self.command("020200")
        for line in resp.split("\n"):
            b = self._hex_bytes(line)
            if len(b) >= 5 and b[0] == 0x42 and b[1] == 0x02:
                code = dtc_mod.decode_dtc(b[3], b[4])
                if code:
                    out["dtc"] = code
                break

        wanted = pids or pids_mod.DASHBOARD_PIDS
        for pid in wanted:
            if pid not in pids_mod.PIDS:
                continue
            resp = self.command(f"02{pid:02X}00")
            if self._is_error(resp):
                continue
            for line in resp.split("\n"):
                b = self._hex_bytes(line)
                if len(b) >= 3 and b[0] == 0x42 and b[1] == pid:
                    decoded = pids_mod.decode(pid, b[3:])  # skip frame byte
                    if decoded is not None:
                        name, value, unit = decoded
                        out["values"].append((pid, name, value, unit))
                    break
        return out

    # --- Mode 06: on-board monitor test results --------------------------
    def supported_mids(self) -> set[int]:
        """Walk the Mode-06 support bitmaps (mirrors supported_pids)."""
        found: set[int] = set()
        for base in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0):
            resp = self.command(f"06{base:02X}")
            if self._is_error(resp):
                break
            bitmap = None
            for line in resp.split("\n"):
                b = self._hex_bytes(line)
                if len(b) >= 6 and b[0] == 0x46 and b[1] == base:
                    bitmap = b[2:6]
                    break
            if bitmap is None:
                break
            value = (bitmap[0] << 24) | (bitmap[1] << 16) | (bitmap[2] << 8) | bitmap[3]
            for i in range(32):
                if value & (1 << (31 - i)):
                    found.add(base + i + 1)
            if not (value & 0x1):
                break
        for marker in (0x20, 0x40, 0x60, 0x80, 0xA0):
            found.discard(marker)
        return found

    def read_mode06(self) -> list:
        """Return a list of mode06.TestResult for every supported monitor."""
        results = []
        for mid in sorted(self.supported_mids()):
            resp = self.command(f"06{mid:02X}")
            if self._is_error(resp):
                continue
            tokens: list[str] = []
            for line in resp.split("\n"):
                for tok in line.split():
                    if tok.endswith(":"):       # ISO-TP frame counter
                        continue
                    tokens.append(tok)
            data = self._hex_bytes("".join(tokens))
            if 0x46 in data:
                data = data[data.index(0x46) + 1:]
            results.extend(mode06_mod.parse(data))
        return results

    # --- Mode 09: vehicle information ------------------------------------
    def _mode09_payload(self, pid: int) -> list[int]:
        """Bytes after the '49 <pid> <count>' header, across frames."""
        resp = self.command(f"09{pid:02X}")
        if self._is_error(resp):
            return []
        payload: list[int] = []
        for line in resp.split("\n"):
            b = self._hex_bytes(line)
            if not b:
                continue
            if 0x49 in b:
                idx = b.index(0x49)
                payload.extend(b[idx + 3:])     # skip 49 <pid> <count>
            else:
                payload.extend(b)
        return payload

    def read_vehicle_info(self) -> dict:
        """Mode 09 extras: calibration id, CVN, and ECU name."""
        info = {}

        def _ascii(payload):
            return "".join(chr(c) for c in payload if 32 <= c <= 126).strip()

        cal = _ascii(self._mode09_payload(0x04))
        if cal:
            info["Calibration ID"] = cal
        cvn = self._mode09_payload(0x06)
        if cvn:
            info["Calibration Verification (CVN)"] = " ".join(
                f"{c:02X}" for c in cvn)
        ecu = _ascii(self._mode09_payload(0x0A))
        if ecu:
            info["ECU name"] = ecu
        return info

    # --- generic service / actuator command runner -----------------------
    NRC = {
        0x10: "general reject", 0x11: "service not supported",
        0x12: "sub-function not supported", 0x13: "wrong message length",
        0x22: "conditions not correct", 0x31: "request out of range",
        0x33: "security access denied", 0x35: "invalid key",
        0x78: "response pending", 0x7E: "service not supported in session",
        0x7F: "service not supported in active session",
    }

    def run_command(self, cmd: str, expect_prefix: int | None = None) -> dict:
        """Send one OBD/UDS command and interpret the reply for the Service tab.

        Returns {"raw", "ok", "detail"}. A '7F <svc> <nrc>' reply is decoded to
        a human reason (e.g. 'security access denied') so a rejected actuator
        request is reported honestly rather than as a silent failure.
        """
        raw = self.command(cmd)
        result = {"raw": raw, "ok": False, "detail": ""}
        if self._is_error(raw):
            result["detail"] = raw or "no response"
            return result
        flat = self._hex_bytes(raw.replace("\n", " ").replace(" ", ""))
        if 0x7F in flat:
            i = flat.index(0x7F)
            nrc = flat[i + 2] if i + 2 < len(flat) else None
            reason = self.NRC.get(nrc, f"code 0x{nrc:02X}" if nrc is not None else "?")
            result["detail"] = f"ECU rejected request: {reason}"
            return result
        if expect_prefix is not None:
            result["ok"] = expect_prefix in flat
            result["detail"] = ("Positive response."
                                if result["ok"] else "Unexpected response.")
        else:
            result["ok"] = True
            result["detail"] = "Command sent."
        return result

    # --- Mode 01 PID 01: readiness monitors ------------------------------
    def read_monitors(self) -> dict:
        resp = self.command("0101")
        if self._is_error(resp):
            return {}
        b = []
        for line in resp.split("\n"):
            bb = self._hex_bytes(line)
            if len(bb) >= 6 and bb[0] == 0x41 and bb[1] == 0x01:
                b = bb[2:6]
                break
        if len(b) < 4:
            return {}
        A, B, C, D = b[0], b[1], b[2], b[3]
        mil = bool(A & 0x80)
        dtc_count = A & 0x7F
        result = {
            "MIL (check engine lamp)": "ON" if mil else "off",
            "Stored DTC count": str(dtc_count),
        }
        # Continuous monitors (B low nibble availability, high nibble status)
        cont = [
            ("Misfire monitor", 0x01),
            ("Fuel system monitor", 0x02),
            ("Components monitor", 0x04),
        ]
        for name, mask in cont:
            if B & mask:
                result[name] = "NOT ready" if (B & (mask << 4)) else "Ready"
            else:
                result[name] = "n/a"
        # Non-continuous monitors are spark-ignition (B3 bit clear => spark)
        non_cont = [
            ("Catalyst", 0x01),
            ("Heated catalyst", 0x02),
            ("EVAP system", 0x04),
            ("Secondary air", 0x08),
            ("O2 sensor", 0x20),
            ("O2 sensor heater", 0x40),
            ("EGR system", 0x80),
        ]
        for name, mask in non_cont:
            if C & mask:
                result[name] = "NOT ready" if (D & mask) else "Ready"
            else:
                result[name] = "n/a"
        return result
