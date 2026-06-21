from agent_runtime.turn_intent import build_turn_intent_frame


def test_turn_intent_does_not_treat_task_with_go_ahead_as_confirmation():
    frame = build_turn_intent_frame("go ahead and check SITL instances now")

    assert frame.route == "read_only"
    assert frame.confirmation_message is False
    assert frame.read_only_plan.intent == "sitl_help"


def test_turn_intent_exact_draft_confirmation_stays_deterministic():
    frame = build_turn_intent_frame("confirm action act-91709278")

    assert frame.route == "action_confirmation"
    assert frame.confirmation_message is True
    assert frame.explicit_action_draft_id == "act-91709278"


def test_turn_intent_motion_advisory_questions_do_not_draft_actions():
    prompts = (
        "tell me if drone 1 should land",
        "show me landing status for drone 1",
        "can drone 1 RTL safely?",
    )

    for prompt in prompts:
        frame = build_turn_intent_frame(prompt)
        assert frame.route != "action_draft", prompt
        assert frame.action.draft is None


def test_turn_intent_direct_motion_commands_still_draft_guarded_actions():
    land = build_turn_intent_frame("land drone 1 now")
    rtl = build_turn_intent_frame("RTL drone 1 now")

    assert land.route == "action_draft"
    assert land.action.draft is not None
    assert land.action.draft.public_payload()["mission_name"] == "LAND"
    assert land.action.draft.public_payload()["target_drone_ids"] == ["1"]

    assert rtl.route == "action_draft"
    assert rtl.action.draft is not None
    assert rtl.action.draft.public_payload()["mission_name"] == "RETURN_RTL"
    assert rtl.action.draft.public_payload()["target_drone_ids"] == ["1"]


def test_turn_intent_compound_pm_prompt_builds_sequence_not_confirmation():
    message = (
        "ok send it to test flight. lets takeoff to 10m, then wait 10s, "
        "then to 10m north same altitude and then return land"
    )
    frame = build_turn_intent_frame(
        message,
        previous_action={"target_drone_ids": ["1"]},
    )

    assert frame.route == "action_draft"
    assert frame.confirmation_message is False
    assert frame.action.draft is not None
    payload = frame.action.draft.public_payload()
    assert payload["mission_name"] == "TAKE_OFF"
    assert payload["target_drone_ids"] == ["1"]
    assert payload["command_payload"]["takeoff_altitude"] == 10.0
    assert [item["type"] for item in payload["post_actions"]] == [
        "delay",
        "flight_command",
        "flight_command",
    ]
    assert payload["post_actions"][1]["arguments"]["precision_move"]["translation_m"]["north"] == 10.0
    assert payload["post_actions"][2]["arguments"]["mission_type"] == 104


def test_turn_intent_uses_semantic_routing_message_for_typo_heavy_sitl_action():
    frame = build_turn_intent_frame(
        "crete one sitl intstance and report when ready to test and fly with",
        semantic_routing_message="create one SITL instance and report when ready to test and fly with",
    )

    assert frame.route == "action_draft"
    assert frame.action.sitl_lifecycle_request is True
    assert frame.action.draft is not None
    payload = frame.action.draft.public_payload()
    assert payload["tool_id"] == "mds.sitl.instances.create"
    assert payload["monitor_requested"] is True
