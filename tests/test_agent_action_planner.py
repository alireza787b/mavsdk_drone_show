from agent_runtime.action_planner import (
    build_flight_action_draft,
    is_action_confirmation_message,
    looks_like_direct_flight_action_request,
)


def test_send_it_compound_flight_prompt_is_fresh_action_not_confirmation():
    message = (
        "ok send it to test flight. lets takeoff to 10m, then wait 10s, "
        "then to 10m north same altitude and then return land"
    )

    assert not is_action_confirmation_message(message)
    assert looks_like_direct_flight_action_request(message)

    draft = build_flight_action_draft(
        message,
        draft_id="act-test123",
        previous_action={"target_drone_ids": ["1"]},
    )

    assert draft is not None
    assert draft.ready
    assert draft.mission_name == "TAKE_OFF"
    assert draft.target_drone_ids == ("1",)
    assert draft.target_inferred_from in {
        "previous_submitted_action",
        "single_previous_action_target",
    }
    assert draft.command_payload["takeoff_altitude"] == 10.0
    assert [item["type"] for item in draft.post_actions] == [
        "delay",
        "flight_command",
        "flight_command",
    ]
    assert draft.post_actions[0]["delay_seconds"] == 10.0
    assert draft.post_actions[1]["action_label"] == "precision move"
    assert draft.post_actions[1]["arguments"]["precision_move"]["translation_m"]["north"] == 10.0
    assert draft.post_actions[2]["action_label"] == "return rtl"


def test_bare_confirmation_still_works_without_new_action_plan():
    assert is_action_confirmation_message("send it")
    assert is_action_confirmation_message("confirm action act-91709278")
    assert is_action_confirmation_message("go ahead")


def test_retrospective_sequence_question_is_not_a_new_flight_action():
    message = "just one question . did you also do teh waits between takeoff and precission move ? or skipped that?"

    assert not looks_like_direct_flight_action_request(message)
    assert build_flight_action_draft(
        message,
        draft_id="act-history",
        previous_action={"target_drone_ids": ["1"]},
    ) is None
