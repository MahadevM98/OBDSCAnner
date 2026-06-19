#!/usr/bin/env python3
"""
BLE diagnostic for the OBD scanner — independent of the GUI.

Usage:
  python3 tools/ble_scan.py                 # scan and list nearby BLE devices
  python3 tools/ble_scan.py AA:BB:CC:DD:EE:FF   # probe one device: connect +
                                                # list its GATT characteristics

This isolates Bluetooth issues from the app: if this can connect and print
characteristics, the app will too (and it tells us the exact write/notify
UUIDs to use). If this fails, the message says why.
"""
import asyncio
import sys


async def scan():
    from bleak import BleakScanner
    print("Scanning 8 s for BLE devices (make sure the adapter is powered "
          "— ignition ON)…\n")
    found = await BleakScanner.discover(timeout=8.0, return_adv=True)
    if not found:
        print("  No BLE devices seen at all. Is Bluetooth on "
              "(`bluetoothctl power on`) and the adapter powered?")
        return
    rows = sorted(found.values(), key=lambda da: -(da[1].rssi or -999))
    for dev, adv in rows:
        name = dev.name or adv.local_name or "(no name)"
        mark = "  <-- looks like OBD" if _is_obd(name) else ""
        print(f"  {dev.address}   RSSI={adv.rssi:>4}   {name}{mark}")
    print("\nRun again with the MAC of your adapter to test a real connection, "
          "e.g.:\n  python3 tools/ble_scan.py " + rows[0][0].address)


def _is_obd(name: str) -> bool:
    up = (name or "").upper()
    return any(k in up for k in ("OBD", "ELM", "VLINK", "VGATE", "VEEPEAK"))


async def probe(mac: str):
    from bleak import BleakClient, BleakScanner
    print(f"Looking for {mac} over an LE scan…")
    dev = await BleakScanner.find_device_by_address(mac, timeout=12.0)
    if dev is None:
        print("  NOT FOUND in the LE scan.\n"
              "  • Confirm the MAC from a plain scan: python3 tools/ble_scan.py\n"
              "  • Power the adapter (ignition ON) and keep it close.\n"
              f"  • If it was ever classic-paired: bluetoothctl remove {mac}")
        return
    print(f"  found: {dev.address}  {dev.name!r}\n  connecting…")
    try:
        async with BleakClient(dev, timeout=20.0) as client:
            print("  CONNECTED. GATT characteristics:\n")
            for service in client.services:
                print(f"  service {service.uuid}")
                for ch in service.characteristics:
                    print(f"    char {ch.uuid}  props={ch.properties}")
            print("\n  ^ Send me these lines if the app still won't connect — "
                  "I'll map the write/notify UUIDs.")
    except Exception as e:
        print(f"  CONNECT FAILED: {e!r}\n"
              f"  If this mentions BR/EDR / ProfileUnavailable, run:\n"
              f"    bluetoothctl remove {mac}\n"
              f"    bluetoothctl power off && bluetoothctl power on\n"
              f"  then retry. Do NOT 'pair' the device.")


async def main():
    try:
        import bleak  # noqa: F401
    except ImportError:
        print("bleak is not installed. Run: sudo apt install python3-bleak")
        return
    if len(sys.argv) > 1:
        await probe(sys.argv[1].strip())
    else:
        await scan()


if __name__ == "__main__":
    asyncio.run(main())
