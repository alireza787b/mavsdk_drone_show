from src.command_execution_contract import (
    format_pending_superseded_execution_error,
    format_superseded_execution_error,
    is_legacy_schema_outcome_rejection,
    is_legacy_superseded_execution_error,
)


def test_legacy_supersede_recognition_accepts_only_safe_historical_shapes():
    assert is_legacy_superseded_execution_error(
        format_superseded_execution_error("Precision move stopped after SIGTERM.")
    )
    assert is_legacy_superseded_execution_error(
        format_pending_superseded_execution_error("HOLD")
    )
    assert not is_legacy_superseded_execution_error(
        "Superseded by a newer command and force-killed before safety cleanup was confirmed"
    )


def test_legacy_schema_fallback_requires_exact_unknown_outcome_error():
    extra_outcome = {
        "detail": [
            {
                "type": "extra_forbidden",
                "loc": ["body", "outcome"],
            }
        ]
    }
    contradictory_outcome = {
        "detail": [
            {
                "type": "value_error",
                "loc": ["body"],
            }
        ]
    }

    assert is_legacy_schema_outcome_rejection(
        status_code=422,
        response_payload=extra_outcome,
    )
    assert not is_legacy_schema_outcome_rejection(
        status_code=422,
        response_payload=contradictory_outcome,
    )
    assert not is_legacy_schema_outcome_rejection(
        status_code=409,
        response_payload=extra_outcome,
    )
