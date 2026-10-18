// Relationship layout only: depth and order never represent aircraft position.
export function swarmDiagramRows(members) {
  const byId = new Map(members.map((member) => [String(member.hw_id), member]));
  const children = new Map();
  members.forEach((member) => {
    const parent = String(member.follow);
    if (parent !== '0' && parent !== String(member.hw_id) && byId.has(parent)) {
      children.set(parent, [...(children.get(parent) || []), member]);
    }
  });
  const rows = [];
  const seen = new Set();
  const visit = (member, depth) => {
    const id = String(member.hw_id);
    if (seen.has(id)) return;
    seen.add(id);
    rows.push({ member, depth });
    (children.get(id) || []).forEach((child) => visit(child, depth + 1));
  };
  members.filter((member) => String(member.follow) === '0' || !byId.has(String(member.follow)))
    .forEach((member) => visit(member, 0));
  // Invalid draft cycles must remain visible and editable.
  members.forEach((member) => visit(member, 0));
  return rows;
}

export function swarmNodeStatus(member, node, { stale = false, hasSession = false, now = Date.now() } = {}) {
  if (!member.available) return { label: 'Offline', tone: 'warning', symbol: '×' };
  if (!hasSession) return { label: 'Not following', tone: 'neutral', symbol: '—' };
  if (stale || !node || !Number.isFinite(node.received_at_ms) || now - node.received_at_ms > 15000) {
    return { label: 'Unconfirmed', tone: 'warning', symbol: '?' };
  }
  const phases = {
    active: ['Following', 'success', '✓'], tracking: ['Following', 'success', '✓'],
    acquiring: ['Joining', 'info', '↗'], settling: ['Settling', 'info', '↗'],
    tracking_degraded: ['Data delayed', 'warning', '!'], holding: ['Paused', 'warning', 'Ⅱ'],
    takeover: ['Pilot control', 'info', 'Ⅱ'], stopped: ['Stopped', 'neutral', '—'],
    failed: ['Failed', 'danger', '!'],
  };
  const [label, tone, symbol] = phases[node.phase] || ['Unconfirmed', 'warning', '?'];
  return { label: label === 'Following' && String(member.follow) === '0' ? 'Leading' : label, tone, symbol };
}
