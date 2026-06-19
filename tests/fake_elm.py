"""A fake ELM327 transport that emulates a Honda Accord ECU, for offline tests.

It speaks just enough of the protocol to exercise the driver: AT commands,
Mode 01 PIDs (incl. support bitmaps), Mode 03/07/0A DTCs, Mode 04 clear,
Mode 09 VIN.
"""

from __future__ import annotations


class FakeELMTransport:
    def __init__(self):
        self._buf = b""
        self.is_open = False
        self.cleared = False

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def write(self, data: bytes):
        cmd = data.decode("ascii").strip().upper().replace(" ", "")
        self._buf = (self._respond(cmd) + "\r>").encode("ascii")

    def read(self, n=1) -> bytes:
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    # ---- canned responses ----
    def _respond(self, cmd: str) -> str:
        if cmd.startswith("AT"):
            return {
                "ATZ": "ELM327 v1.5",
                "ATE0": "OK", "ATL0": "OK", "ATS0": "OK", "ATH0": "OK",
                "ATSP0": "OK", "ATI": "ELM327 v1.5",
                "ATDPN": "6", "ATDP": "AUTO, ISO 15765-4 (CAN 11/500)",
                "ATRV": "13.9V",
            }.get(cmd, "OK")

        # Mode 01 support bitmaps
        if cmd == "0100":
            return "41 00 BE 3E B8 13"   # advertises a typical PID set
        if cmd == "0120":
            return "41 20 80 07 B0 11"
        if cmd == "0140":
            return "41 40 00 00 00 00"   # no further blocks

        # Mode 01 PIDs (sample live values)
        pid_data = {
            "0101": "41 01 00 07 E1 00",   # MIL off, monitors
            "010C": "41 0C 0F A0",          # 1000 rpm
            "010D": "41 0D 28",             # 40 km/h
            "0105": "41 05 5A",             # 50 C coolant
            "010F": "41 0F 46",             # 30 C intake
            "0104": "41 04 80",             # ~50% load
            "0111": "41 11 33",             # ~20% throttle
            "0110": "41 10 03 E8",          # 10 g/s MAF
            "0106": "41 06 84",             # +3% STFT
            "0107": "41 07 7E",             # -1.5% LTFT
            "010E": "41 0E 80",             # 0 deg timing
            "010B": "41 0B 23",             # 35 kPa MAP
            "0133": "41 33 65",             # 101 kPa baro
            "012F": "41 2F BF",             # ~75% fuel
            "0142": "41 42 36 B0",          # 14.0 V
        }
        if cmd in pid_data:
            return pid_data[cmd]

        # Mode 02 freeze frame: mirror Mode-01 data with a 42 + frame byte.
        if cmd.startswith("02") and len(cmd) >= 6:
            pid = cmd[2:4]
            if pid == "02":
                return "42 02 00 03 01"          # frozen by P0301
            src = pid_data.get("01" + pid)
            if src:
                return "42 " + pid + " 00 " + " ".join(src.split()[2:])
            return "NO DATA"

        # Mode 06 on-board monitor results (support bitmaps + two records).
        if cmd == "0600":
            return "46 00 80 00 00 01"           # MID 0x01 + next block
        if cmd == "0620":
            return "46 20 80 00 00 00"           # MID 0x21 (catalyst)
        if cmd == "0601":
            return "46 01 01 0A 00 80 00 40 00 C0"   # O2 monitor: PASS
        if cmd == "0621":
            return "46 21 80 10 01 00 00 50 00 F0"   # catalyst: FAIL (val>max)

        # Mode 09 vehicle info: calibration id / CVN / ECU name.
        if cmd == "0904":
            cal = "PNB6A100"
            return "49 04 01 " + " ".join(f"{ord(c):02X}" for c in cal)
        if cmd == "0906":
            return "49 06 01 12 34 56 78"
        if cmd == "090A":
            name = "ECM-HONDA"
            return "49 0A 01 " + " ".join(f"{ord(c):02X}" for c in name)

        # Service / UDS functions.
        if cmd == "1103":
            return "51 03"
        if cmd == "1101":
            return "51 01"
        if cmd == "080100":
            return "48 01 00"
        if cmd == "1003":
            return "50 03"
        if cmd == "3E00":
            return "7E 00"

        # Mode 03 stored DTCs: P0301 + P0420
        if cmd == "03":
            if self.cleared:
                return "43 00"
            return "43 02 03 01 04 20"
        # Mode 07 pending: P0171
        if cmd == "07":
            return "47 01 01 71"
        # Mode 0A permanent: P0420
        if cmd == "0A":
            return "4A 01 04 20"
        # Mode 22 Honda enhanced (experimental): only ATF temp answered here
        if cmd == "221101":                 # VTC cam advance angle
            return "62 11 01 3C"            # 60/2 = 30 deg
        if cmd == "22115C":                 # transmission fluid temp
            return "62 11 5C 78"            # 0x78 - 40 = 80 C
        # Mode 04 clear
        if cmd == "04":
            self.cleared = True
            return "44"
        # Mode 09 VIN (single-frame style ascii for "1HGCP2..." example)
        if cmd == "0902":
            # 49 02 01 + 17 ascii bytes of a sample Accord VIN
            vin = "1HGCP26478A012345"
            hexv = " ".join(f"{ord(c):02X}" for c in vin)
            return f"49 02 01 {hexv}"

        return "NO DATA"
