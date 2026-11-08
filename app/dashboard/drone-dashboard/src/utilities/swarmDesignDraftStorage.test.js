import { readSwarmDesignDraft } from './swarmDesignDraftStorage';

const plan = [
  { hw_id: '1', follow: '0', offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
  { hw_id: '2', follow: '1', offset_x: 6, offset_y: 0, offset_z: 0, frame: 'ned' },
];
const edited = plan.map(row => ({ ...row, offset_x: row.hw_id === '2' ? 9 : 0 }));

test('base comparison ignores order and numeric representation, not formation changes', () => {
  const base = [...plan].reverse().map(row => ({ ...row, hw_id: Number(row.hw_id), offset_x: String(row.offset_x) }));
  expect(readSwarmDesignDraft({ base, assignments: edited }, plan)).toMatchObject({ automatic: true, changed: true, assignments: edited });
  expect(readSwarmDesignDraft({ base: edited, assignments: edited }, plan).automatic).toBe(false);
});

test('legacy array recovery retains the follow relationships', () => {
  expect(readSwarmDesignDraft(edited, plan)).toMatchObject({ automatic: false, changed: true,
    assignments: [expect.objectContaining({ follow: '0' }), expect.objectContaining({ follow: '1', offset_x: 9 })] });
});

test('an already-applied draft does not create a recovery warning', () => {
  expect(readSwarmDesignDraft({ base: edited, assignments: plan }, plan)).toBeNull();
  expect(readSwarmDesignDraft(plan, plan)).toBeNull();
  expect(readSwarmDesignDraft({ base: plan, assignments: plan }, plan).changed).toBe(false);
});

test('restored native capture metadata retains the inactive-apply guard', () => {
  const capture = { hwIds: ['1', '2'], captureId: 'capture-1', heightMode: 'level' };
  expect(readSwarmDesignDraft({ base: edited, assignments: edited, capture, previewHeadings: { 1: 90 } }, plan))
    .toMatchObject({ automatic: false, metadata: { capture, previewHeadings: { 1: 90 } } });
});

test.each([null, {}, { assignments: [] }, { assignments: [null] }, { assignments: [plan[0], plan[0]] }])(
  'invalid drafts do not replace the saved plan: %p', value => {
    expect(readSwarmDesignDraft(value, plan)).toBeNull();
  }
);
