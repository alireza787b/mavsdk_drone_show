import pytest

from tools.runtime_validation_support import require_sitl_runtime_status


def test_require_sitl_runtime_status_accepts_reconciled_sitl():
    payload = {
        "mode": "sitl",
        "configured_mode": "sitl",
        "configured_sim_mode": True,
        "restart_required": False,
    }

    assert require_sitl_runtime_status(payload) is payload


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mode": "real",
            "configured_mode": "real",
            "configured_sim_mode": False,
            "restart_required": False,
        },
        {
            "mode": "real",
            "configured_mode": "sitl",
            "configured_sim_mode": True,
            "restart_required": True,
        },
        {
            "mode": "sitl",
            "configured_mode": "real",
            "configured_sim_mode": False,
            "restart_required": True,
        },
    ],
)
def test_require_sitl_runtime_status_rejects_real_or_mismatched_target(payload):
    with pytest.raises(RuntimeError, match="Refusing SITL validation"):
        require_sitl_runtime_status(payload)
