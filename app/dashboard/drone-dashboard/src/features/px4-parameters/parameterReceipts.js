const LIMIT = 48;
export const isReceiptUncertain = receipt => !receipt.job || receipt.job.terminal !== true || receipt.job.status === 'unknown'
  || (receipt.job.unknown_targets || 0) > 0;

export function newerParameterReceipt(previous, incoming) {
  if (previous?.job?.job_id && previous.job.job_id === incoming.job?.job_id) {
    if (previous.job.terminal === true && incoming.job.terminal !== true) return previous;
    if (Number.isFinite(previous.job.updated_at) && Number.isFinite(incoming.job.updated_at)
      && previous.job.updated_at > incoming.job.updated_at) return previous;
  }
  if (previous?.job && !incoming.job) return { ...previous, error: incoming.error };
  return incoming;
}

function compactReceipt(receipt) {
  const { entries, ...stored } = receipt;
  if (!receipt.job) return stored;
  // Recovery needs identity and observed summaries, not a second unbounded copy
  // of 4,096 native entry results multiplied by every aircraft in the fleet.
  const { results = [], ...job } = receipt.job;
  return { ...stored, job: { ...job, results: results.map(({ result, ...summary }) => summary) } };
}

export function readParameterReceipts(key) {
  const text = localStorage.getItem(key);
  if (!text) return [];
  const records = JSON.parse(text);
  if (!Array.isArray(records) || records.length > LIMIT || records.some(record => !record
    || typeof record.idempotencyKey !== 'string' || !record.idempotencyKey
    || typeof record.reviewId !== 'string' || typeof record.reviewHash !== 'string'
    || !Array.isArray(record.hwIds) || !record.hwIds.length
    || record.hwIds.some(id => typeof id !== 'string' || !id)
    || (record.title !== undefined && typeof record.title !== 'string')
    || (record.excludedHwIds !== undefined && (!Array.isArray(record.excludedHwIds) || record.excludedHwIds.some(id => typeof id !== 'string')))
    || (record.job?.results !== undefined && !Array.isArray(record.job.results)))) throw new Error('Saved parameter receipts are unreadable.');
  return records;
}

/** Persist the request identity before dispatch. Never evict an uncertain write. */
export function saveParameterReceipt(key, receipt) {
  const existing = readParameterReceipts(key);
  const merged = newerParameterReceipt(existing.find(record => record.idempotencyKey === receipt.idempotencyKey), receipt);
  const records = existing.filter(record => record.idempotencyKey !== receipt.idempotencyKey);
  const next = [merged, ...records];
  while (next.length > LIMIT) {
    const index = next.findLastIndex ? next.findLastIndex(record => !isReceiptUncertain(record))
      : next.map(record => !isReceiptUncertain(record)).lastIndexOf(true);
    if (index <= 0) throw new Error('Resolve unconfirmed parameter operations before starting another.');
    next.splice(index, 1);
  }
  const serialized = JSON.stringify(next.map(compactReceipt));
  localStorage.setItem(key, serialized);
  if (localStorage.getItem(key) !== serialized) throw new Error('The recovery receipt could not be saved.');
  return next;
}
