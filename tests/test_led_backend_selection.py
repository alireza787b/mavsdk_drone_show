import builtins
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.led_backends import legacy_pwm_backend_supported


@pytest.mark.parametrize("soc", ["bcm2835", "bcm2836", "bcm2837", "bcm2711"])
def test_known_legacy_soc_can_use_pwm_backend(tmp_path, soc):
    compatible = tmp_path / "compatible"
    compatible.write_bytes(f"raspberrypi,board\0brcm,{soc}\0".encode())
    assert legacy_pwm_backend_supported(compatible)


@pytest.mark.parametrize("contents", [b"brcm,bcm2712\0", b"unknown,board\0", b"", b"brcm,bcm2711\0brcm,bcm2712\0"])
def test_rp1_and_unknown_boards_do_not_use_legacy_backend(tmp_path, contents):
    compatible = tmp_path / "compatible"
    compatible.write_bytes(contents)
    assert not legacy_pwm_backend_supported(compatible)


def test_absent_device_tree_does_not_authorize_native_backend(tmp_path):
    assert not legacy_pwm_backend_supported(tmp_path / "missing")


def test_ineligible_board_never_imports_legacy_native_module(monkeypatch):
    from src.params import Params
    from src import led_backends

    monkeypatch.setattr(Params, "sim_mode", False)
    monkeypatch.setattr(led_backends, "legacy_pwm_backend_supported", lambda: False)
    normal_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "rpi_ws281x":
            pytest.fail("Ineligible native driver was imported")
        if name == "Pi5Neo":
            raise ImportError("Optional SPI backend is not installed")
        return normal_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module_path = Path(__file__).resolve().parents[1] / "src/led_controller.py"
    spec = importlib.util.spec_from_file_location("led_backend_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LED_LIBRARY is None
    assert module.LEDController.get_instance().strip is None


@pytest.mark.parametrize("simulation", [False, True])
def test_supported_legacy_and_simulation_keep_their_existing_paths(monkeypatch, simulation):
    from src.params import Params
    from src import led_backends

    monkeypatch.setattr(Params, "sim_mode", simulation)
    monkeypatch.setattr(led_backends, "legacy_pwm_backend_supported", lambda: True)
    normal_import = builtins.__import__

    class Strip:
        def __init__(self, *args):
            pass

        def begin(self):
            pass

    def guarded_import(name, *args, **kwargs):
        if name in {"rpi_ws281x", "Pi5Neo"}:
            assert not simulation, "Simulation imported a hardware LED backend"
            assert name == "rpi_ws281x", "Supported legacy path was not preserved"
            return SimpleNamespace(PixelStrip=Strip, Color=object())
        return normal_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    path = Path(__file__).resolve().parents[1] / "src/led_controller.py"
    spec = importlib.util.spec_from_file_location("led_legacy_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    controller = module.LEDController.get_instance()
    assert controller.led_library == (None if simulation else "rpi_ws281x")
