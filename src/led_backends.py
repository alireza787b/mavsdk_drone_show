"""Hardware eligibility for MDS's legacy PWM/DMA LED backend."""

from pathlib import Path


def legacy_pwm_backend_supported(
    compatible_path: Path = Path("/proc/device-tree/compatible"),
) -> bool:
    """Only use the legacy driver on its known pre-RP1 Raspberry Pi SoCs.

    Import availability is not a hardware capability check. In particular,
    catching a failed native initialization cannot contain a later segfault.
    RP1-specific kernel-driver integrations are not this legacy backend.
    """
    try:
        compatible = set(compatible_path.read_bytes().split(b"\0"))
    except OSError:
        return False
    if b"brcm,bcm2712" in compatible:
        return False
    return bool(compatible.intersection({
        b"brcm,bcm2835", b"brcm,bcm2836", b"brcm,bcm2837", b"brcm,bcm2711",
    }))
