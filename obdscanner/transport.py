"""
Transport layer for the ELM327 adapter.

Three ways to reach the adapter:

  * BluetoothTransport - opens a raw RFCOMM socket straight to the adapter's
    MAC address. For *classic* Bluetooth (BR/EDR) ELM327 adapters. No
    `sudo rfcomm bind` and no /dev node required; the device only has to be
    paired (or at least pair-able) in bluetoothctl.

  * BLETransport - talks to a *Bluetooth Low Energy* (GATT) adapter, i.e. the
    very common "OBDBLE" / Vgate BLE clones. These do NOT support RFCOMM
    (trying it gives "[Errno 113] No route to host"). Needs the `bleak`
    library; see open() for the install hint.

  * SerialTransport - opens a serial device such as /dev/rfcomm0 or
    /dev/ttyUSB0 using pyserial. Useful for USB ELM327 clones or if you
    prefer the classic `rfcomm bind` workflow.

All expose the same tiny interface used by the ELM327 driver:
    open(), close(), write(bytes), read(n) -> bytes, is_open
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import threading
import time


class TransportError(Exception):
    pass


class BluetoothTransport:
    """Direct RFCOMM socket to an ELM327's Bluetooth MAC address."""

    def __init__(self, mac: str, channel: int = 1, timeout: float = 5.0):
        self.mac = mac.strip().upper()
        self.channel = int(channel)
        self.timeout = timeout
        self._sock: socket.socket | None = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def open(self) -> None:
        if self._sock is not None:
            return
        # Many adapters expose their serial port on a channel other than 1
        # (this one uses 2). Try the SDP-advertised channel(s) first, then the
        # requested one, then the usual fallbacks, so the user need not guess.
        candidates: list[int] = []
        for ch in [*find_spp_channels(self.mac), self.channel, 1, 2, 3]:
            if ch and ch not in candidates:
                candidates.append(ch)
        last_err: Exception | None = None
        for ch in candidates:
            s = socket.socket(
                socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
            )
            s.settimeout(self.timeout)
            try:
                s.connect((self.mac, ch))
            except OSError as e:
                last_err = e
                try:
                    s.close()
                except OSError:
                    pass
                continue
            self._sock = s
            self.channel = ch
            return
        raise TransportError(
            f"Could not open Bluetooth RFCOMM to {self.mac} "
            f"(tried channels {candidates}): {last_err}. "
            "If this is a BLE-only adapter, use the Bluetooth LE option instead."
        )

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportError("Transport not open")
        try:
            self._sock.sendall(data)
        except OSError as e:
            self._drop()
            raise TransportError(f"Bluetooth connection lost on write: {e}") from e

    def read(self, n: int = 1) -> bytes:
        if self._sock is None:
            raise TransportError("Transport not open")
        try:
            return self._sock.recv(n)
        except socket.timeout:
            return b""
        except OSError as e:
            self._drop()
            raise TransportError(f"Bluetooth connection lost on read: {e}") from e


# --- Bluetooth Low Energy (GATT) ----------------------------------------
# Serial-over-BLE profiles used by ELM327 BLE clones, in priority order.
# Each is (write_characteristic_uuid, notify_characteristic_uuid).
_BLE_PROFILES = [
    ("0000fff2-0000-1000-8000-00805f9b34fb",   # Vgate / many "OBDBLE" clones
     "0000fff1-0000-1000-8000-00805f9b34fb"),
    ("0000ffe1-0000-1000-8000-00805f9b34fb",   # HM-10 style (one shared char)
     "0000ffe1-0000-1000-8000-00805f9b34fb"),
    ("6e400002-b5a3-f393-e0a9-e50e24dcca9e",   # Nordic UART service
     "6e400003-b5a3-f393-e0a9-e50e24dcca9e"),
]


def _has_write(props) -> bool:
    return "write" in props or "write-without-response" in props


def _needs_response(props) -> bool:
    # If the characteristic only advertises plain "write", it expects a
    # response; "write-without-response" is the faster fire-and-forget mode.
    return "write-without-response" not in props


def select_ble_uuids(chars):
    """Pick (write_uuid, write_response, notify_uuid) from a device's
    characteristics. `chars` is a list of (uuid, properties) where properties
    is an iterable of strings like 'write', 'notify'. Raises TransportError if
    no usable serial-style pair is found. Pure function — unit-testable."""
    by = {str(u).lower(): set(p) for u, p in chars}
    for write_u, notify_u in _BLE_PROFILES:
        if (write_u in by and notify_u in by
                and _has_write(by[write_u])
                and ({"notify", "indicate"} & by[notify_u])):
            return write_u, _needs_response(by[write_u]), notify_u
    # Generic fallback: any writable char + any notifying char.
    notify_u = next((u for u, p in by.items() if {"notify", "indicate"} & p), None)
    write_u = next((u for u, p in by.items() if _has_write(p)), None)
    if write_u and notify_u:
        return write_u, _needs_response(by[write_u]), notify_u
    raise TransportError(
        "No serial-style BLE characteristics found on this adapter. "
        "Discovered: " + ", ".join(sorted(by)) or "(none)")


class BLETransport:
    """Bluetooth Low Energy (GATT) transport for BLE ELM327 adapters.

    bleak is async; we run a private asyncio loop on a background thread and
    drive it synchronously so the rest of the app keeps its simple
    open/write/read interface. Incoming GATT notifications are buffered and
    handed out by read()."""

    def __init__(self, mac: str, timeout: float = 12.0):
        self.mac = mac.strip().upper()
        self.timeout = timeout
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._rx = bytearray()
        self._lock = threading.Lock()
        self._write_uuid = ""
        self._notify_uuid = ""
        self._write_response = False

    @property
    def is_open(self) -> bool:
        return self._client is not None

    def _run(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(self.timeout + 5)

    def open(self) -> None:
        if self._client is not None:
            return
        try:
            from bleak import BleakClient  # noqa: F401
        except ImportError as e:
            raise TransportError(
                "Bluetooth LE needs the 'bleak' library, which is not "
                "installed. Install it with one of:\n"
                "    sudo apt install python3-bleak\n"
                "    python3 -m pip install --user bleak\n"
                "Then make sure Bluetooth is on: bluetoothctl power on"
            ) from e

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        daemon=True)
        self._thread.start()
        try:
            self._run(self._connect())
        except TransportError:
            self._teardown_loop()
            raise
        except Exception as e:
            self._teardown_loop()
            raise TransportError(
                f"Could not open BLE connection to {self.mac}: {e}. "
                "Is Bluetooth powered on and the adapter in range?") from e

    async def _connect(self):
        from bleak import BleakClient, BleakScanner
        # Discover the adapter over an LE scan first. Passing the resulting
        # BLEDevice (rather than a bare MAC) makes BlueZ use the LE transport;
        # a bare MAC can make it try classic BR/EDR and fail with
        # "org.bluez.Error.BREDR.ProfileUnavailable" when the device was once
        # paired as a classic device.
        device = await BleakScanner.find_device_by_address(self.mac,
                                                           timeout=self.timeout)
        if device is None:
            raise TransportError(
                f"BLE device {self.mac} was not found while scanning. "
                "Make sure it is powered (ignition ON), in range, and not "
                "already connected elsewhere. If it was paired as a classic "
                "device, run:  bluetoothctl remove " + self.mac)
        client = BleakClient(device, timeout=self.timeout)
        await client.connect()
        chars = []
        for service in client.services:
            for ch in service.characteristics:
                chars.append((ch.uuid, list(ch.properties)))
        self._write_uuid, self._write_response, self._notify_uuid = \
            select_ble_uuids(chars)
        await client.start_notify(self._notify_uuid, self._on_notify)
        self._client = client

    def _on_notify(self, _sender, data: bytearray):
        with self._lock:
            self._rx.extend(bytes(data))

    def write(self, data: bytes) -> None:
        if self._client is None:
            raise TransportError("Transport not open")
        try:
            self._run(self._client.write_gatt_char(
                self._write_uuid, bytes(data), response=self._write_response))
        except Exception as e:
            raise TransportError(f"BLE write failed: {e}") from e

    def read(self, n: int = 1) -> bytes:
        with self._lock:
            out = bytes(self._rx[:n])
            del self._rx[:n]
        return out

    def close(self) -> None:
        if self._client is not None:
            try:
                self._run(self._client.disconnect())
            except Exception:
                pass
            self._client = None
        self._teardown_loop()

    def _teardown_loop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
            self._thread = None


class SerialTransport:
    """Serial-port transport (e.g. /dev/rfcomm0, /dev/ttyUSB0)."""

    def __init__(self, port: str, baudrate: int = 38400, timeout: float = 5.0):
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = timeout
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(self) -> None:
        try:
            import serial  # pyserial
        except ImportError as e:
            raise TransportError(
                "pyserial is required for serial transport (import serial failed)"
            ) from e
        try:
            self._ser = serial.serial_for_url(
                self.port, baudrate=self.baudrate, timeout=self.timeout,
                write_timeout=self.timeout,
            ) if "://" in self.port else serial.Serial(
                self.port, baudrate=self.baudrate, timeout=self.timeout,
                write_timeout=self.timeout,
            )
        except Exception as e:  # serial.SerialException et al.
            raise TransportError(f"Could not open serial port {self.port}: {e}") from e

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise TransportError("Transport not open")
        self._ser.write(data)

    def read(self, n: int = 1) -> bytes:
        if self._ser is None:
            raise TransportError("Transport not open")
        return self._ser.read(n)


def find_spp_channels(mac: str) -> list[int]:
    """RFCOMM channel(s) that advertise a serial profile, discovered via
    `sdptool records <mac>`. Returns [] if sdptool is unavailable, the device
    is unreachable, or no serial channel is published. Best-effort only."""
    try:
        res = subprocess.run(
            ["sdptool", "records", str(mac)],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    channels: list[int] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("Channel:"):
            try:
                ch = int(line.split(":", 1)[1].strip())
            except ValueError:
                continue
            if ch not in channels:
                channels.append(ch)
    return channels


def list_paired_devices() -> list[tuple[str, str]]:
    """Return [(mac, name), ...] of Bluetooth devices known to bluetoothctl.

    Uses `bluetoothctl devices`. Returns an empty list if bluetoothctl is
    unavailable or errors out.
    """
    out_devices: list[tuple[str, str]] = []
    for args in (["bluetoothctl", "devices"], ["bluetoothctl", "devices", "Paired"]):
        try:
            res = subprocess.run(
                args, capture_output=True, text=True, timeout=10
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        for line in res.stdout.splitlines():
            # Format: "Device AA:BB:CC:DD:EE:FF Name Here"
            parts = line.strip().split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device":
                mac = parts[1]
                name = parts[2] if len(parts) > 2 else mac
                if not any(mac == m for m, _ in out_devices):
                    out_devices.append((mac, name))
        if out_devices:
            break
    return out_devices
