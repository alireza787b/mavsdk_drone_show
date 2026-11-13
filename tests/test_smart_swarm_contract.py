from src.smart_swarm_contract import (
    dependency_closed_targets, normalize_topology, resolve_clusters,
    topology_revision, SmartSwarmSession, required_reference_ids,
)
import pytest


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


def test_scoped_start_requires_exact_upstream_references_without_promoting():
    members = normalize_topology(topology())
    assert required_reference_ids(members, ['3']) == ['1', '2']
    original = [dict(row) for row in members]
    session = SmartSwarmSession(assignments=members, revision=topology_revision(members),
        expected_hw_ids=['3'], reference_hw_ids=['1','2'])
    assert session.expected_hw_ids == ['3']
    assert members == original
    assert session.model_dump()['reference_hw_ids'] == ['1','2']
    for refs in [[], ['1'], ['1','2','3'], ['1','1','2']]:
        with pytest.raises(ValueError):
            SmartSwarmSession(assignments=members, revision=topology_revision(members),
                expected_hw_ids=['3'], reference_hw_ids=refs)


def test_normal_session_wire_contract_stays_compatible_with_older_nodes():
    members = normalize_topology(topology())
    session = SmartSwarmSession(assignments=members, revision=topology_revision(members), expected_hw_ids=['1','2','3'])
    assert 'reference_hw_ids' not in session.model_dump()
