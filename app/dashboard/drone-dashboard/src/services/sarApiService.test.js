import axios from 'axios';
import {
  abortMission,
  batchElevation,
  computePlan,
  getMissionWorkspace,
  listMissions,
  updatePOI,
} from './sarApiService';
import { buildSarUrl } from './gcsApiService';

jest.mock('axios');
jest.mock('./gcsApiService', () => ({
  buildSarUrl: jest.fn((suffix = '') => `http://gcs.test:5000/api/sar${suffix}`),
}));

describe('sarApiService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    buildSarUrl.mockImplementation((suffix = '') => `http://gcs.test:5000/api/sar${suffix}`);
  });

  it('uses the centralized SAR base route with planning timeout defaults', async () => {
    axios.post.mockResolvedValue({ data: { mission_id: 'sar-1' } });

    await computePlan({ search_area: { type: 'polygon', points: [] } });

    expect(buildSarUrl).toHaveBeenCalledWith('/mission/plan');
    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/sar/mission/plan',
      { search_area: { type: 'polygon', points: [] } },
      { timeout: 30000 }
    );
  });

  it('lists persisted QuickScout missions through the shared SAR route builder', async () => {
    axios.get.mockResolvedValue({ data: { missions: [], count: 0 } });

    await listMissions({ limit: 5, state: 'ready' });

    expect(buildSarUrl).toHaveBeenCalledWith('/missions?limit=5&state=ready');
    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5000/api/sar/missions?limit=5&state=ready');
  });

  it('encodes mission ids and repeated drone filters for abort requests', async () => {
    axios.post.mockResolvedValue({ data: { success: true } });

    await abortMission('mission/alpha', ['1', '2'], 'hold_position');

    expect(buildSarUrl).toHaveBeenCalledWith(
      '/mission/mission%2Falpha/abort?return_behavior=hold_position&pos_ids=1&pos_ids=2'
    );
    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/sar/mission/mission%2Falpha/abort?return_behavior=hold_position&pos_ids=1&pos_ids=2'
    );
  });

  it('encodes mission ids for workspace recovery requests', async () => {
    axios.get.mockResolvedValue({ data: { operation: { mission_id: 'mission/alpha' } } });

    await getMissionWorkspace('mission/alpha');

    expect(buildSarUrl).toHaveBeenCalledWith('/mission/mission%2Falpha/workspace');
    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/sar/mission/mission%2Falpha/workspace'
    );
  });

  it('encodes POI ids and delegates payload updates through the shared SAR route builder', async () => {
    axios.patch.mockResolvedValue({ data: { id: 'poi/1', label: 'updated' } });

    await updatePOI('poi/1', { label: 'updated' });

    expect(buildSarUrl).toHaveBeenCalledWith('/poi/poi%2F1');
    expect(axios.patch).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/sar/poi/poi%2F1',
      { label: 'updated' }
    );
  });

  it('delegates batch elevation payloads through the shared SAR API surface', async () => {
    axios.post.mockResolvedValue({ data: [{ elevation: 12 }] });

    await batchElevation([{ lat: 1, lng: 2 }]);

    expect(buildSarUrl).toHaveBeenCalledWith('/elevation/batch');
    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/sar/elevation/batch',
      [{ lat: 1, lng: 2 }]
    );
  });
});
