import { saveSwarmPlan } from './saveSwarmPlan';
import { saveSwarmConfigResponse, publishSwarmConfigResponse } from '../services/gcsApiService';
jest.mock('../services/gcsApiService', () => ({ saveSwarmConfigResponse: jest.fn(), publishSwarmConfigResponse: jest.fn() }));
beforeEach(() => jest.clearAllMocks());

test('a rejected Apply never publishes', async () => {
  saveSwarmConfigResponse.mockRejectedValue(new Error('Conflict'));
  await expect(saveSwarmPlan({ needsApply: true, publish: true, revision: 'old' })).rejects.toThrow('Conflict');
  expect(publishSwarmConfigResponse).not.toHaveBeenCalled();
});
test('publication failure records the successful Apply and exact returned revision', async () => {
  saveSwarmConfigResponse.mockResolvedValue({ data: { config: { revision: 'new' } } });
  publishSwarmConfigResponse.mockRejectedValue(new Error('Network failure'));
  await expect(saveSwarmPlan({ needsApply: true, publish: true, revision: 'old' })).rejects.toMatchObject({ saveStage: 'publish', planApplied: true, appliedRevision: 'new' });
  expect(publishSwarmConfigResponse).toHaveBeenCalledWith('new');
});

test('captured drafts require the complete captured scope inactive at Apply', async () => {
  saveSwarmConfigResponse.mockResolvedValue({ data: { config: { revision: 'new' } } });
  await saveSwarmPlan({ assignments: [], needsApply: true, publish: false, revision: 'old', requireInactiveHwIds: ['1', '2'] });
  expect(saveSwarmConfigResponse).toHaveBeenCalledWith([], {
    commit: false, revision: 'old', acknowledgedUnavailableIds: [], requireInactiveHwIds: ['1', '2'],
  });
});
