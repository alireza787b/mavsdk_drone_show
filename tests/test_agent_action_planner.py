from agent_runtime.action_planner import (
    build_flight_action_draft,
    build_sitl_reconcile_action_draft,
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


def test_conditional_ready_prompt_still_drafts_guarded_sequence():
    message = (
        "I see its up. if its rady to fly send it to a mission. "
        "lets takeoff 10m then wait 10s, then fly to 20m east, "
        "then wait 30s, then RTL"
    )

    assert not is_action_confirmation_message(message)
    assert looks_like_direct_flight_action_request(message)

    draft = build_flight_action_draft(
        message,
        draft_id="act-conditional",
        previous_action={"target_drone_ids": ["1"]},
    )

    assert draft is not None
    assert draft.ready
    assert draft.mission_name == "TAKE_OFF"
    assert draft.target_drone_ids == ("1",)
    assert draft.command_payload["takeoff_altitude"] == 10.0
    assert [item["type"] for item in draft.post_actions] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert draft.post_actions[0]["delay_seconds"] == 10.0
    assert draft.post_actions[1]["arguments"]["precision_move"]["translation_m"] == {
        "north": 0.0,
        "east": 20.0,
        "up": 0.0,
    }
    assert draft.post_actions[2]["delay_seconds"] == 30.0
    assert draft.post_actions[3]["action_label"] == "return rtl"


def test_compound_status_then_build_one_sitl_keeps_singular_create_clause():
    draft = build_sitl_reconcile_action_draft(
        "How many drones are configured and how many SITL are active? Then build one.",
        draft_id="act-buildone",
        conversation_topic="sitl",
    )

    assert draft is not None
    assert draft.tool_id == "mds.sitl.instances.create"
    assert draft.arguments == {
        "git_sync_enabled": True,
        "requirements_sync_enabled": True,
    }
    assert draft.missing_arguments == ()


def test_then_separated_moves_are_ordered_not_combined():
    message = (
        "Ok now lets use drone of for below mission. Takeoff to 14m, then for 5m south. "
        "Then climb 10m again. Then wait 5s. Then return and report"
    )

    assert looks_like_direct_flight_action_request(message)

    draft = build_flight_action_draft(
        message,
        draft_id="act-seqpm",
        previous_action={"target_drone_ids": ["1"]},
    )

    assert draft is not None
    assert draft.ready
    assert draft.mission_name == "TAKE_OFF"
    assert draft.target_drone_ids == ("1",)
    assert draft.command_payload["takeoff_altitude"] == 14.0
    assert [item["type"] for item in draft.post_actions] == [
        "flight_command",
        "flight_command",
        "delay",
        "flight_command",
    ]
    south_move = draft.post_actions[0]["arguments"]["precision_move"]["translation_m"]
    climb_move = draft.post_actions[1]["arguments"]["precision_move"]["translation_m"]
    assert south_move == {"north": -5.0, "east": 0.0, "up": 0.0}
    assert climb_move == {"north": 0.0, "east": 0.0, "up": 10.0}
    assert draft.post_actions[2]["delay_seconds"] == 5.0
    assert draft.post_actions[3]["action_label"] == "return rtl"


def test_same_clause_motion_components_stay_combined():
    message = "takeoff drone 1 to 10m then go 10m east and climb 3m at same time then rtl"

    draft = build_flight_action_draft(message, draft_id="act-combined")

    assert draft is not None
    assert draft.ready
    assert [item["type"] for item in draft.post_actions] == ["flight_command", "flight_command"]
    translation = draft.post_actions[0]["arguments"]["precision_move"]["translation_m"]
    assert translation == {"north": 0.0, "east": 10.0, "up": 3.0}
    assert draft.post_actions[1]["action_label"] == "return rtl"


def test_comma_separated_moves_are_ordered_steps():
    message = "takeoff drone 1 to 14m, 5m south, climb 10m, wait 5s, return and report"

    draft = build_flight_action_draft(message, draft_id="act-comma")

    assert draft is not None
    assert draft.ready
    assert [item["type"] for item in draft.post_actions] == [
        "flight_command",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert draft.post_actions[0]["arguments"]["precision_move"]["translation_m"] == {
        "north": -5.0,
        "east": 0.0,
        "up": 0.0,
    }
    assert draft.post_actions[1]["arguments"]["precision_move"]["translation_m"] == {
        "north": 0.0,
        "east": 0.0,
        "up": 10.0,
    }
    assert draft.post_actions[2]["delay_seconds"] == 5.0
    assert draft.post_actions[3]["action_label"] == "return rtl"


def test_return_to_launch_and_report_drafts_one_rtl():
    message = "takeoff drone 1 to 14m then return to launch and report"

    draft = build_flight_action_draft(message, draft_id="act-rtl")

    assert draft is not None
    assert draft.ready
    assert [item["action_label"] for item in draft.post_actions] == ["return rtl"]


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
