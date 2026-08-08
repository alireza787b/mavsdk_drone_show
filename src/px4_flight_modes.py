"""PX4 ``HEARTBEAT.custom_mode`` decoding shared by node runtime code.

PX4 stores a reserved uint16 followed by one byte each for ``main_mode`` and
``sub_mode``.  Keeping this protocol knowledge here prevents mission scripts
and telemetry processing from growing independent numeric lookup tables.
"""

PX4_CUSTOM_MAIN_MODE_SHIFT = 16
PX4_CUSTOM_SUB_MODE_SHIFT = 24
PX4_CUSTOM_MODE_BYTE_MASK = 0xFF

PX4_MAIN_MODE_MANUAL = 1
PX4_MAIN_MODE_ALTCTL = 2
PX4_MAIN_MODE_POSCTL = 3
PX4_MAIN_MODE_AUTO = 4
PX4_MAIN_MODE_ACRO = 5
PX4_MAIN_MODE_OFFBOARD = 6
PX4_MAIN_MODE_STABILIZED = 7
PX4_MAIN_MODE_RATTITUDE_LEGACY = 8
PX4_MAIN_MODE_SIMPLE = 9
PX4_MAIN_MODE_TERMINATION = 10
PX4_MAIN_MODE_ALTITUDE_CRUISE = 11

PX4_MAIN_MODE_NAMES = {
    PX4_MAIN_MODE_MANUAL: "Manual",
    PX4_MAIN_MODE_ALTCTL: "Altitude",
    PX4_MAIN_MODE_ACRO: "Acro",
    PX4_MAIN_MODE_OFFBOARD: "Offboard",
    PX4_MAIN_MODE_STABILIZED: "Stabilized",
    PX4_MAIN_MODE_RATTITUDE_LEGACY: "Rattitude",
    PX4_MAIN_MODE_SIMPLE: "Simple",
    PX4_MAIN_MODE_TERMINATION: "Termination",
    PX4_MAIN_MODE_ALTITUDE_CRUISE: "Altitude Cruise",
}

PX4_POSCTL_SUB_MODE_NAMES = {
    0: "Position",
    1: "Orbit",
    2: "Position Slow",
}

PX4_AUTO_SUB_MODE_NAMES = {
    0: "Auto",
    1: "Ready",
    2: "Takeoff",
    3: "Hold",
    4: "Mission",
    5: "Return",
    6: "Land",
    7: "Auto Reserved",
    8: "Follow Target",
    9: "Precision Land",
    10: "VTOL Takeoff",
    11: "External 1",
    12: "External 2",
    13: "External 3",
    14: "External 4",
    15: "External 5",
    16: "External 6",
    17: "External 7",
    18: "External 8",
    19: "Guided Course",
    20: "Descend",
}


def decode_px4_custom_mode(custom_mode: int | None) -> tuple[int, int]:
    """Return the PX4 ``(main_mode, sub_mode)`` bytes from custom_mode."""
    mode = int(custom_mode or 0)
    main_mode = (mode >> PX4_CUSTOM_MAIN_MODE_SHIFT) & PX4_CUSTOM_MODE_BYTE_MASK
    sub_mode = (mode >> PX4_CUSTOM_SUB_MODE_SHIFT) & PX4_CUSTOM_MODE_BYTE_MASK
    return main_mode, sub_mode


def describe_px4_custom_mode(custom_mode: int | None) -> str:
    """Return a stable operator-facing name for a raw PX4 custom_mode."""
    mode = int(custom_mode or 0)
    if mode == 0:
        return "Unknown/Uninit"

    main_mode, sub_mode = decode_px4_custom_mode(mode)
    if main_mode == PX4_MAIN_MODE_POSCTL:
        return PX4_POSCTL_SUB_MODE_NAMES.get(sub_mode, f"Position({sub_mode})")
    if main_mode == PX4_MAIN_MODE_AUTO:
        return PX4_AUTO_SUB_MODE_NAMES.get(sub_mode, f"Auto({sub_mode})")
    if main_mode in PX4_MAIN_MODE_NAMES:
        return PX4_MAIN_MODE_NAMES[main_mode]
    return f"Unknown({mode})"
