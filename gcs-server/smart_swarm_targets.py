"""Validate reviewed cluster scope without owning aircraft admission or control."""
from src.smart_swarm_contract import dependency_closed_targets, resolve_clusters


def validate_cluster_targets(assignments, targets, excluded=(), unavailable=()):
    included, omitted = set(targets), set(excluded)
    clusters = resolve_clusters(assignments)
    cluster = next((item for item in clusters
                    if included | omitted == {m['hw_id'] for m in item['members']}), None)
    if cluster is None or not included or included & omitted:
        raise ValueError('Select a complete saved cluster before starting Smart Swarm')
    if omitted:
        allowed = {m['hw_id'] for m in cluster['members']} - set(
            dependency_closed_targets(cluster['members'], list(unavailable)))
        if omitted != allowed:
            raise ValueError('Availability changed; review the partial-start confirmation')
    if included != set(dependency_closed_targets(cluster['members'], list(omitted))):
        raise ValueError('Include each follower’s upstream leader')
    return cluster
