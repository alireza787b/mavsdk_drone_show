from src.smart_swarm_contract import (
    dependency_closed_targets, normalize_topology, resolve_clusters,
    topology_revision, SmartSwarmSession,
)


def topology():
    return [
        {"hw_id": 1, "follow": 0},
        {"hw_id": 2, "follow": 1, "offset_x": 6},
        {"hw_id": 3, "follow": 2, "offset_x": 12},
    ]


def test_cluster_resolution_and_revision_are_deterministic():
    assert resolve_clusters(topology())[0]["cluster_id"] == "1"
    assert [m["hw_id"] for m in resolve_clusters(topology())[0]["members"]] == ["1", "2", "3"]
    assert topology_revision(topology()) == topology_revision(list(reversed(topology())))


def test_partial_start_never_orphans_descendants():
    members = normalize_topology(topology())
    assert dependency_closed_targets(members, ["2"]) == ["1"]
    assert dependency_closed_targets(members, ["1"]) == []


def test_session_requires_current_revision_and_closed_dependencies():
    members = normalize_topology(topology())
    revision = topology_revision(members)
    session = SmartSwarmSession(revision=revision, assignments=members, expected_hw_ids=["1", "2"])
    assert session.expected_hw_ids == ["1", "2"]
