export async function uploadLeaderTrajectoryCsv({
  leaderId,
  csvContent,
  waypoints = null,
  buildCsv = null,
  uploadFn,
}) {
  if (!leaderId) {
    throw new Error('Choose a top-level leader before assigning a route.');
  }
  if (typeof uploadFn !== 'function') {
    throw new Error('Leader route upload is unavailable.');
  }

  const csv = csvContent ?? buildCsv?.(waypoints || []);
  if (!csv || typeof csv !== 'string') {
    throw new Error('No leader route CSV was produced.');
  }

  const blob = new Blob([csv], { type: 'text/csv' });
  const result = await uploadFn(leaderId, blob, `Drone ${leaderId}.csv`);
  if (!result?.success) {
    throw new Error(result?.error || result?.message || 'Upload failed');
  }
  return result;
}
