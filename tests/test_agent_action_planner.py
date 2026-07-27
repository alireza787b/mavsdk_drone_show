import json
from types import SimpleNamespace

from agent_runtime import action_planner
from agent_runtime.action_planner import (
    FlightActionDraft,
    RegistryActionDraft,
    action_draft_from_context_json,
    build_flight_action_draft,
    build_sitl_reconcile_action_draft,
    is_action_confirmation_message,
    looks_like_direct_flight_action_request,
)
from agent_runtime.action_preconditions import ActionPrecondition


class _ToolRegistryStub:
    def __init__(self, monitor_kinds):
        self._monitor_kinds = monitor_kinds

    def require(self, tool_id):
        return SimpleNamespace(
            assistant_action={"monitor_kind": self._monitor_kinds.get(tool_id, "none")}
        )


def test_registry_action_draft_round_trips_typed_preconditions():
    draft = RegistryActionDraft(
        draft_id="act-conditional-roundtrip",
        tool_id="mds.sitl.instances.create",
        tool_title="Create SITL instance",
        intent="sitl_lifecycle_action",
        action_label="create SITL instance",
        arguments={"git_sync_enabled": True},
        monitor_requested=True,
        wait_condition="operation_terminal_success",
        preconditions=(
            ActionPrecondition(
                fact_id="sitl.running_instance_count",
                arguments={},
                operator="eq",
                expected=0,
                label="No SITL instance is running",
            ),
        ),
    )

    restored = action_draft_from_context_json(draft.to_context_json())

    assert isinstance(restored, RegistryActionDraft)
    assert restored.public_payload() == draft.public_payload()


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
    assert draft.arguments == {}
    assert draft.missing_arguments == ()


def test_sitl_primary_monitoring_comes_from_registry_not_operator_wording(monkeypatch):
    monitor_kinds = {
        "mds.sitl.instances.create": "sitl_operation",
        "mds.sitl.instances.action": "sitl_operation",
        "mds.sitl.fleet.reconcile": "sitl_operation",
    }
    monkeypatch.setattr(
        action_planner,
        "load_default_tool_registry",
        lambda: _ToolRegistryStub(monitor_kinds),
    )

    terse_prompts = (
        ("create one SITL instance", "mds.sitl.instances.create"),
        ("remove SITL instance drone-1", "mds.sitl.instances.action"),
        ("create 4 SITL instances", "mds.sitl.fleet.reconcile"),
    )
    terse_drafts = [
        build_sitl_reconcile_action_draft(prompt, draft_id=f"act-terse-{index}")
        for index, (prompt, _tool_id) in enumerate(terse_prompts, start=1)
    ]
    verbose = build_sitl_reconcile_action_draft(
        "create one SITL instance and report progress until done",
        draft_id="act-verbose",
    )

    assert all(draft is not None for draft in terse_drafts)
    assert [draft.tool_id for draft in terse_drafts if draft is not None] == [
        tool_id for _prompt, tool_id in terse_prompts
    ]
    assert all(draft.monitor_requested is True for draft in terse_drafts if draft is not None)
    assert verbose is not None and verbose.monitor_requested is True

    monitor_kinds["mds.sitl.instances.create"] = "none"
    no_monitor_contract = build_sitl_reconcile_action_draft(
        "create one SITL instance and report progress until done",
        draft_id="act-contract-none",
    )
    assert no_monitor_contract is not None
    assert no_monitor_contract.monitor_requested is False


def test_dependent_sitl_cleanup_requires_registry_declared_terminal_monitoring(monkeypatch):
    monkeypatch.setattr(
        action_planner,
        "load_default_tool_registry",
        lambda: _ToolRegistryStub({"mds.sitl.instances.action": "sitl_operation"}),
    )

    draft = build_flight_action_draft(
        "land drone 1 then remove the SITL instance",
        draft_id="act-cleanup",
    )

    assert draft is not None and draft.ready
    cleanup = draft.post_actions[-1]
    assert cleanup["tool_id"] == "mds.sitl.instances.action"
    assert cleanup["monitor_requested"] is True
    assert cleanup["wait_condition"] == "operation_terminal_success"


def test_targetless_flight_draft_is_never_ready_even_when_missing_arguments_are_empty():
    draft = FlightActionDraft.from_context_json(
        json.dumps(
            {
                "draft_type": "flight_action",
                "draft_id": "act-targetless",
                "mission_name": "LAND",
                "mission_type": 101,
                "target_drone_ids": [],
                "command_payload": {
                    "mission_type": 101,
                    "target_drone_ids": [],
                    "trigger_time": 0,
                },
                "missing_arguments": [],
            }
        )
    )

    assert draft.missing_arguments == ()
    assert draft.target_drone_ids == ()
    assert draft.ready is False


def test_registry_action_draft_context_round_trip_preserves_ordered_sequence():
    draft = RegistryActionDraft(
        draft_id="act-registry-sequence",
        tool_id="mds.sitl.instances.create",
        tool_title="Create SITL instance",
        intent="sitl_lifecycle_action",
        action_label="Create SITL instance",
        arguments={},
        monitor_requested=True,
        wait_condition="operation_terminal_success",
        post_actions=(
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "action_label": "Take off to 10 m",
                "condition": "after_command_terminal_success",
                "arguments": {
                    "mission_type": 10,
                    "trigger_time": 0,
                    "takeoff_altitude": 10,
                    "target_drone_ids": [],
                },
                "target_from_previous_result": True,
                "monitor_requested": True,
                "wait_condition": "command_terminal_success",
            },
        ),
    )

    restored = RegistryActionDraft.from_context_json(draft.to_context_json())

    assert restored == draft


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


def test_direct_precision_moves_keep_order_and_do_not_treat_distance_as_target():
    draft = build_flight_action_draft(
        "move drone 1 10m north, then move 5m east",
        draft_id="act-direct-moves",
    )

    assert draft is not None
    assert draft.ready
    assert draft.mission_name == "PRECISION_MOVE"
    assert draft.target_drone_ids == ("1",)
    assert draft.command_payload["precision_move"]["translation_m"] == {
        "north": 10.0,
        "east": 0.0,
        "up": 0.0,
    }
    assert len(draft.post_actions) == 1
    assert draft.post_actions[0]["arguments"]["precision_move"]["translation_m"] == {
        "north": 0.0,
        "east": 5.0,
        "up": 0.0,
    }


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


def test_two_canonical_waits_between_moves_remain_ordered_steps():
    message = (
        "take off drone 1 to 10m, then wait for 5s, then go 25m north, "
        "then wait 5s, then climb 10m up, then return and land"
    )

    draft = build_flight_action_draft(message, draft_id="act-two-pauses")

    assert draft is not None
    assert draft.ready
    assert [item["type"] for item in draft.post_actions] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
        "flight_command",
    ]
    assert draft.post_actions[0]["delay_seconds"] == 5.0
    assert draft.post_actions[1]["arguments"]["precision_move"]["translation_m"] == {
        "north": 25.0,
        "east": 0.0,
        "up": 0.0,
    }
    assert draft.post_actions[2]["delay_seconds"] == 5.0
    assert draft.post_actions[3]["arguments"]["precision_move"]["translation_m"] == {
        "north": 0.0,
        "east": 0.0,
        "up": 10.0,
    }
    assert draft.post_actions[4]["action_label"] == "return rtl"


def test_unresolved_timed_step_is_not_silently_dropped():
    draft = build_flight_action_draft(
        "take off drone 1 to 10m, hold there for 5s, move 25m north, then RTL",
        draft_id="act-unresolved-hold",
    )

    assert draft is not None
    assert not draft.ready
    assert "sequence_timing" in draft.missing_arguments
    assert [item["type"] for item in draft.post_actions] == ["flight_command", "flight_command"]


def test_yaw_is_an_ordered_sequence_step_and_can_share_a_motion_clause():
    separate = build_flight_action_draft(
        "takeoff drone 1 to 10m, yaw to 290 degrees, then RTL",
        draft_id="act-yaw-step",
    )
    simultaneous = build_flight_action_draft(
        "takeoff drone 1 to 10m, yaw to 290 degrees and climb 3m at the same time, then RTL",
        draft_id="act-yaw-climb",
    )

    assert separate is not None and separate.ready
    assert simultaneous is not None and simultaneous.ready
    separate_move = separate.post_actions[0]["arguments"]["precision_move"]
    simultaneous_move = simultaneous.post_actions[0]["arguments"]["precision_move"]
    assert separate_move["translation_m"] == {"north": 0.0, "east": 0.0, "up": 0.0}
    assert separate_move["yaw"] == {"mode": "absolute_heading", "degrees": 290.0}
    assert simultaneous_move["translation_m"] == {"north": 0.0, "east": 0.0, "up": 3.0}
    assert simultaneous_move["yaw"] == {"mode": "absolute_heading", "degrees": 290.0}
    assert separate.post_actions[-1]["condition"] == "after_command_terminal_success"
    assert simultaneous.post_actions[-1]["condition"] == "after_command_terminal_success"


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
