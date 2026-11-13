/** Advisory display of saved upstream links, never edits or flight admission. */
export function swarmReferenceIds(members, targets) {
  const byId = new Map(members.map(row => [String(row.hw_id), row]));
  const included = new Set(targets), references = new Set();
  for (const id of targets) {
    const seen = new Set([id]);
    let parent = String(byId.get(id)?.follow || '0');
    while (parent !== '0' && byId.has(parent) && !seen.has(parent)) {
      seen.add(parent);
      if (!included.has(parent)) references.add(parent);
      parent = String(byId.get(parent).follow);
    }
  }
  return [...references].sort((a,b) => Number(a)-Number(b));
}

export function swarmStartQuery(clusterId, targets) {
  return new URLSearchParams([['cluster_id', clusterId], ['check_start', 'true'],
    ...targets.map(id => ['target_hw_ids', id])]);
}

export function swarmReviewEvidence(reviewed, data, requestedAt, validUntil) {
  const references = reviewed.references || [];
  const confirmed = data.reference_hw_ids || [];
  if (references.length !== confirmed.length || references.some(id => !confirmed.includes(id))) return null;
  const decisions = { ...data.start_admissions, ...Object.fromEntries(references.map(id => [id, {
    ...data.reference_admissions?.[id], message: `Leader reference: ${data.reference_admissions?.[id]?.message || 'Checking aircraft'}`,
  }])) };
  return { decisions, until: validUntil([...reviewed.targets, ...references], decisions, requestedAt) };
}
