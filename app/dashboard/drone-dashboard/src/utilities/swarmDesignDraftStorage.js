import { getDirtyAssignmentIds, normalizeSwarmAssignment } from './swarmDesignUtils';

const samePlan = (left, right) => Array.isArray(left) && left.length === right.length
  && left.every(row => row && typeof row === 'object')
  && new Set(left.map(row => String(row?.hw_id))).size === right.length
  && getDirtyAssignmentIds(left, right).length === 0;

/** Browser recovery is a draft, never an applied plan or flight authority. */
export function readSwarmDesignDraft(stored, baseline) {
  const saved = Array.isArray(stored) ? { assignments: stored } : stored;
  if (!Array.isArray(saved?.assignments) || !saved.assignments.length) return null;
  const assignments = saved.assignments.map(row => row && normalizeSwarmAssignment(row));
  if (assignments.some(row => !row)
      || new Set(assignments.map(row => row.hw_id)).size !== assignments.length) return null;
  const sameBase = samePlan(saved.base, baseline);
  const changed = !samePlan(assignments, baseline);
  // An already-applied draft is not a conflict, including legacy array storage.
  if (!sameBase && !changed) return null;
  return {
    assignments,
    changed,
    metadata: { previewHeadings: saved.previewHeadings || {},
      ...(saved.capture?.hwIds?.length ? { capture: saved.capture } : {}) },
    automatic: sameBase && assignments.length === baseline.length
      && assignments.every(row => baseline.some(item => String(item.hw_id) === row.hw_id)),
  };
}
