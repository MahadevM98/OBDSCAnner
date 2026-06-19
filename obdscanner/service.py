"""
Service / actuator functions: commands that *write* to the vehicle rather than
just read from it.

SCOPE AND HONESTY
-----------------
A generic ELM327 on the OBD-II port can reliably do exactly one standardised
"reset": Mode 04 (clear DTCs), which on most ECUs also drops emission readiness
and some learned fuel/idle adaptives. Everything below Mode 04 here is UDS /
manufacturer territory: the ECU is free to reject it (and usually will without
a security-access handshake). We send the request and report the ECU's answer
honestly, including negative-response reasons.

There is NO standardised OBD-II command that performs a Honda throttle-body /
idle relearn. That lives in Honda's proprietary HDS protocol and is not exposed
through a plain ELM327. What actually works on these cars is the documented
key-on idle-learn *procedure* (see IDLE_RELEARN_PROCEDURE), optionally after a
Mode 04 clear. We do not ship fabricated "secret" Honda bytes that could put the
ECU in an unknown state.

Each entry:
  id        - stable key
  title     - button label
  steps     - list of raw commands sent in order (stop on hard error)
  expect    - response byte that signals success for the last step (or None)
  risk      - "safe" | "caution"  (caution -> extra confirmation in the GUI)
  engine    - required engine state shown to the user before running
  detail    - what it does / caveats
"""

from __future__ import annotations

COMMANDS = [
    {
        "id": "clear_dtc",
        "title": "Clear DTCs + reset adaptives (Mode 04)",
        "steps": ["04"],
        "expect": 0x44,
        "risk": "safe",
        "engine": "Key ON, engine OFF",
        "detail": "Standard erase of stored/pending codes and freeze frame. "
                  "Also turns off the MIL and, on most ECUs, resets emission "
                  "readiness monitors and learned fuel/idle trims. This is the "
                  "closest standard equivalent to a 'throttle/idle reset'.",
    },
    {
        "id": "ecu_reset_soft",
        "title": "ECU soft reset (UDS 11 03)",
        "steps": ["1103"],
        "expect": 0x51,
        "risk": "caution",
        "engine": "Key ON, engine OFF",
        "detail": "UDS softReset. Asks the engine ECU to restart its software. "
                  "Most Hondas reject this without security access — the ECU's "
                  "refusal reason is shown if so. Harmless when rejected.",
    },
    {
        "id": "ecu_reset_hard",
        "title": "ECU hard reset (UDS 11 01)",
        "steps": ["1101"],
        "expect": 0x51,
        "risk": "caution",
        "engine": "Key ON, engine OFF",
        "detail": "UDS hardReset (power-on reset of the ECU). Same caveats as "
                  "the soft reset; commonly rejected on consumer ECUs.",
    },
    {
        "id": "evap_leak_test",
        "title": "EVAP leak test (Mode 08 TID 01)",
        "steps": ["080100"],
        "expect": 0x48,
        "risk": "caution",
        "engine": "Engine running, warm",
        "detail": "Requests the on-board EVAP system leak test (Mode 08 is the "
                  "standard 'control of on-board component' service). Support is "
                  "rare on Honda; the ECU answers 0x48 if it accepts it.",
    },
    {
        "id": "ext_session",
        "title": "Enter extended diagnostic session (UDS 10 03)",
        "steps": ["1003"],
        "expect": 0x50,
        "risk": "caution",
        "engine": "Key ON, engine OFF",
        "detail": "Switches the ECU into the extended session some routines "
                  "require. On its own it changes nothing permanent; sessions "
                  "time out on their own. Pair with Tester Present to hold it.",
    },
    {
        "id": "tester_present",
        "title": "Tester present (UDS 3E 00)",
        "steps": ["3E00"],
        "expect": 0x7E,
        "risk": "safe",
        "engine": "Any",
        "detail": "Keep-alive ping. Useful to confirm the ECU answers UDS at "
                  "all and to hold an extended session open.",
    },
]


# Documented Honda idle / throttle relearn. This is a procedure, not a packet.
IDLE_RELEARN_PROCEDURE = """\
Honda idle / throttle-body relearn (no proprietary command required)

Do this after cleaning the throttle body, replacing the battery, or clearing
codes, when the idle hunts or hangs.

  1. Reset adaptives first: run "Clear DTCs + reset adaptives (Mode 04)" above
     with the key ON and engine OFF (or disconnect the battery for ~3 minutes).
  2. Start the engine and bring it to full operating temperature — let it run
     until the radiator cooling fan cycles on at least once.
  3. Turn OFF every accessory: A/C, headlights, blower fan, rear defogger,
     audio. Headlights off, doors closed.
  4. Put the transmission in Park (AT) or Neutral (MT). Do NOT touch the
     throttle.
  5. Let the engine idle undisturbed for ~10 minutes. The ECU relearns the
     closed-throttle position and base idle during this period.
  6. Switch off, restart, and confirm the idle is smooth and steady.

Note: a true HDS "throttle position learn" uses Honda's proprietary protocol
and cannot be triggered through a generic ELM327. The procedure above achieves
the same relearn through the ECU's normal idle-learn logic.
"""
