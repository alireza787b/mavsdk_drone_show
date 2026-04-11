from types import SimpleNamespace

import pytest

import origin


def test_compute_origin_from_drone_accepts_low_residual_non_success(monkeypatch):
    monkeypatch.setattr(
        origin,
        "minimize",
        lambda *args, **kwargs: SimpleNamespace(
            success=False,
            message="ABNORMAL_TERMINATION_IN_LNSRCH",
            fun=5.123889543883753e-07,
            x=[35.724435686078365, 51.275581311948706],
        ),
    )

    lat, lon = origin.compute_origin_from_drone(
        35.7243908,
        51.2756092,
        -5.0,
        2.5,
    )

    assert lat == pytest.approx(35.724435686078365)
    assert lon == pytest.approx(51.275581311948706)


def test_compute_origin_from_drone_rejects_non_success_high_residual(monkeypatch):
    monkeypatch.setattr(
        origin,
        "minimize",
        lambda *args, **kwargs: SimpleNamespace(
            success=False,
            message="ABNORMAL_TERMINATION_IN_LNSRCH",
            fun=0.75,
            x=[35.724435686078365, 51.275581311948706],
        ),
    )

    with pytest.raises(Exception, match="Optimization failed"):
        origin.compute_origin_from_drone(
            35.7243908,
            51.2756092,
            -5.0,
            2.5,
        )
