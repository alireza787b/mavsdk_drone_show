import { isReceiptUncertain, newerParameterReceipt, readParameterReceipts, saveParameterReceipt } from './parameterReceipts';

const receipt = key => ({ idempotencyKey: key, reviewId: 'review', reviewHash: 'hash', hwIds: ['1'], job: null });
afterEach(() => localStorage.clear());
test('persists exact recovery identity and distinguishes unknown from verified', () => {
  const saved = receipt('request-1');
  saveParameterReceipt('px4-test', saved);
  expect(readParameterReceipts('px4-test')).toEqual([saved]);
  expect(isReceiptUncertain(saved)).toBe(true);
  expect(isReceiptUncertain({ ...saved, job: { terminal: true, status: 'unknown', unknown_targets: 1 } })).toBe(true);
  expect(isReceiptUncertain({ ...saved, job: { terminal: true, status: 'completed', unknown_targets: 0 } })).toBe(false);
});
test('does not overwrite malformed receipts or evict uncertain writes', () => {
  localStorage.setItem('broken', '{bad json');
  expect(() => saveParameterReceipt('broken', receipt('one'))).toThrow();
  expect(localStorage.getItem('broken')).toBe('{bad json');
  for (let index = 0; index < 48; index += 1) saveParameterReceipt('full', receipt(`request-${index}`));
  expect(() => saveParameterReceipt('full', receipt('overflow'))).toThrow(/Resolve/);
  expect(readParameterReceipts('full')).toHaveLength(48);
});
test('keeps large detailed results in memory but persists compact recoverable summaries', () => {
  const full = { ...receipt('large-result'), entries: Array.from({ length: 4096 }, (_, index) => ({ name: `TEST_${index}`, value: index })),
    job: { job_id: 'job', status: 'completed', terminal: true, unknown_targets: 0,
      results: [{ hw_id: '1', applied: true, verified: true, outcome: 'verified', result: { results: Array.from({ length: 4096 }, (_, index) => ({ name: `TEST_${index}` })) } }] } };
  const memory = saveParameterReceipt('large', full);
  expect(memory[0].job.results[0].result.results).toHaveLength(4096);
  const persisted = readParameterReceipts('large')[0];
  expect(persisted.entries).toBeUndefined();
  expect(persisted.job.results[0]).toEqual({ hw_id: '1', applied: true, verified: true, outcome: 'verified' });
  expect(localStorage.getItem('large').length).toBeLessThan(1000);
});
test('late polling cannot replace terminal evidence with an older queued observation', () => {
  const complete = { ...receipt('same'), job: { job_id: 'job', updated_at: 20, terminal: true, status: 'completed' } };
  const older = { ...receipt('same'), job: { job_id: 'job', updated_at: 10, terminal: false, status: 'queued' } };
  expect(newerParameterReceipt(complete, older)).toBe(complete);
  saveParameterReceipt('ordered', complete);
  saveParameterReceipt('ordered', older);
  expect(readParameterReceipts('ordered')[0].job.status).toBe('completed');
});
