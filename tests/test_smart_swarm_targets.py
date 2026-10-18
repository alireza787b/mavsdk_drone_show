import pytest
from smart_swarm_targets import validate_cluster_targets


LAYOUT = [{'hw_id': 1, 'follow': 0}, {'hw_id': 2, 'follow': 1},
          {'hw_id': 3, 'follow': 2}, {'hw_id': 4, 'follow': 0}]


def test_complete_saved_cluster_accepted():
    assert validate_cluster_targets(LAYOUT, ['1', '2', '3'])['cluster_id'] == '1'


@pytest.mark.parametrize('targets,excluded', [(['1'], []), (['2'], []),
    (['1', '4'], []), (['1'], ['2']), (['1'], ['2', '3', '9']), ([], ['1', '2', '3'])])
def test_no_implicit_subset_or_multiple_clusters(targets, excluded):
    with pytest.raises(ValueError):
        validate_cluster_targets(LAYOUT, targets, excluded)


def test_partial_start_uses_current_unavailable_dependency_closure():
    validate_cluster_targets(LAYOUT, ['1'], ['2', '3'], ['2'])
    with pytest.raises(ValueError, match='Availability changed'):
        validate_cluster_targets(LAYOUT, ['1'], ['2', '3'], [])


def test_partial_cannot_drop_leader_and_keep_follower():
    with pytest.raises(ValueError):
        validate_cluster_targets(LAYOUT, ['2', '3'], ['1'], ['1'])
