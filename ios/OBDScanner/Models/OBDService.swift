import Foundation

/// Service / actuator catalog (ported from service.py). These WRITE to the
/// car. There is no standard OBD-II command for a Honda throttle relearn — the
/// documented idle-relearn procedure is shown instead.
struct ServiceSpec: Identifiable {
    let id: String
    let title: String
    let steps: [String]
    let expect: UInt8?
    let caution: Bool
    let engine: String
    let detail: String
}

enum OBDService {
    static let commands: [ServiceSpec] = [
        ServiceSpec(
            id: "clear_dtc",
            title: "Clear DTCs + reset adaptives (Mode 04)",
            steps: ["04"], expect: 0x44, caution: false,
            engine: "Key ON, engine OFF",
            detail: "Standard erase of stored/pending codes and freeze frame. "
                + "Also turns off the MIL and, on most ECUs, resets emission "
                + "readiness and learned fuel/idle trims. Closest standard "
                + "equivalent to a 'throttle/idle reset'."),
        ServiceSpec(
            id: "ecu_reset_soft",
            title: "ECU soft reset (UDS 11 03)",
            steps: ["1103"], expect: 0x51, caution: true,
            engine: "Key ON, engine OFF",
            detail: "UDS softReset. Most Hondas reject this without security "
                + "access — the refusal reason is shown. Harmless when rejected."),
        ServiceSpec(
            id: "ecu_reset_hard",
            title: "ECU hard reset (UDS 11 01)",
            steps: ["1101"], expect: 0x51, caution: true,
            engine: "Key ON, engine OFF",
            detail: "UDS hardReset (power-on reset). Commonly rejected on "
                + "consumer ECUs."),
        ServiceSpec(
            id: "evap_leak_test",
            title: "EVAP leak test (Mode 08 TID 01)",
            steps: ["080100"], expect: 0x48, caution: true,
            engine: "Engine running, warm",
            detail: "Requests the on-board EVAP leak test. Support is rare on "
                + "Honda; ECU answers 0x48 if accepted."),
        ServiceSpec(
            id: "ext_session",
            title: "Enter extended session (UDS 10 03)",
            steps: ["1003"], expect: 0x50, caution: true,
            engine: "Key ON, engine OFF",
            detail: "Switches the ECU into the extended session some routines "
                + "require. Changes nothing permanent; sessions time out."),
        ServiceSpec(
            id: "tester_present",
            title: "Tester present (UDS 3E 00)",
            steps: ["3E00"], expect: 0x7E, caution: false,
            engine: "Any",
            detail: "Keep-alive ping; confirms the ECU answers UDS at all."),
    ]

    static let idleRelearn = """
    Honda idle / throttle-body relearn (no proprietary command required)

    Do this after cleaning the throttle body, replacing the battery, or clearing \
    codes, when the idle hunts or hangs.

    1. Reset adaptives first: run "Clear DTCs + reset adaptives (Mode 04)" with \
    the key ON and engine OFF (or disconnect the battery for ~3 minutes).
    2. Start the engine and bring it to full operating temperature — let it run \
    until the radiator cooling fan cycles on at least once.
    3. Turn OFF every accessory: A/C, headlights, blower fan, rear defogger, \
    audio. Doors closed.
    4. Put the transmission in Park (AT) or Neutral (MT). Do NOT touch the \
    throttle.
    5. Let the engine idle undisturbed for ~10 minutes. The ECU relearns the \
    closed-throttle position and base idle.
    6. Switch off, restart, and confirm the idle is smooth and steady.

    Note: a true HDS "throttle position learn" uses Honda's proprietary protocol \
    and cannot be triggered through a generic ELM327. The procedure above \
    achieves the same relearn through the ECU's normal idle-learn logic.
    """
}
