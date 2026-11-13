"""Validate reviewed cluster scope without owning aircraft admission or control."""
from src.smart_swarm_contract import required_reference_ids, resolve_clusters


def validate_cluster_targets(assignments, targets, excluded=(), references=()):
    included, omitted, sources = set(targets), set(excluded), set(references)
    clusters = resolve_clusters(assignments)
    cluster = next((item for item in clusters
                    if included | omitted | sources == {m['hw_id'] for m in item['members']}), None)
    if cluster is None or not included or included & omitted or sources & (included | omitted):
        raise ValueError('Select a complete saved cluster before starting Smart Swarm')
    if sources != set(required_reference_ids(cluster['members'], list(targets))):
        raise ValueError('Review the saved upstream leader references')
    return cluster
