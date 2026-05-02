jest.mock('./gcsApiService', () => ({
  buildGcsUrl: jest.fn((routeOrPath) => {
    const routeMap = {
      fleetCandidates: '/api/v1/fleet/candidates',
    };
    const resolved = routeMap[routeOrPath] || routeOrPath;
    return `http://gcs.test:5030${resolved}`;
  }),
  fetchGcsResource: jest.fn(),
  postGcsResource: jest.fn(),
  GCS_ROUTE_KEYS: {
    fleetCandidates: 'fleetCandidates',
  },
  GCS_ROUTES: {
    fleetCandidates: '/api/v1/fleet/candidates',
  },
}));

describe('fleetEnrollmentApiService', () => {
  let service;
  let gcsApi;

  beforeEach(() => {
    jest.resetModules();
    gcsApi = require('./gcsApiService');
    jest.clearAllMocks();
    service = require('./fleetEnrollmentApiService');
  });

  it('builds canonical candidate urls', () => {
    expect(service.buildFleetCandidateUrl()).toBe('http://gcs.test:5030/api/v1/fleet/candidates');
    expect(service.buildFleetCandidateUrl('node/12')).toBe('http://gcs.test:5030/api/v1/fleet/candidates/node%2F12');
    expect(service.buildFleetCandidateUrl('node/12', '/recover')).toBe('http://gcs.test:5030/api/v1/fleet/candidates/node%2F12/recover');
  });

  it('lists and fetches candidates through the canonical registry routes', async () => {
    gcsApi.fetchGcsResource.mockResolvedValue({ data: { candidates: [] } });

    await service.listFleetCandidates({ includeInactive: true });
    await service.getFleetCandidate('hw-101');

    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(
      1,
      'fleetCandidates',
      { params: { include_inactive: 'true', runtime_mode: 'current' } },
    );
    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5030/api/v1/fleet/candidates/hw-101',
    );
  });

  it('posts accept, replace, and recover mutations with explicit commit policy', async () => {
    gcsApi.postGcsResource.mockResolvedValue({ data: { status: 'success' } });

    await service.acceptFleetCandidate('hw-101', { pos_id: 12, mavlink_port: 14550 }, { commit: true });
    await service.replaceFleetCandidate('hw-101', { target_hw_id: 12 }, { commit: false });
    await service.recoverFleetCandidate('node-12b', { mavlink_port: 14620 }, { commit: true });

    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5030/api/v1/fleet/candidates/hw-101/accept',
      { pos_id: 12, mavlink_port: 14550 },
      { params: { commit: 'true' } },
    );
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5030/api/v1/fleet/candidates/hw-101/replace',
      { target_hw_id: 12 },
      { params: { commit: 'false' } },
    );
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      3,
      'http://gcs.test:5030/api/v1/fleet/candidates/node-12b/recover',
      { mavlink_port: 14620 },
      { params: { commit: 'true' } },
    );
  });

  it('posts announce, reject, and ignore mutations through canonical routes', async () => {
    gcsApi.postGcsResource.mockResolvedValue({ data: { status: 'success' } });

    await service.announceFleetCandidate({ hw_id: '101' });
    await service.rejectFleetCandidate('hw-101', { reason: 'duplicate' });
    await service.ignoreFleetCandidate('hw-101', { reason: 'bench spare' });

    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5030/api/v1/fleet/candidates/announce',
      { hw_id: '101' },
    );
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5030/api/v1/fleet/candidates/hw-101/reject',
      { reason: 'duplicate' },
    );
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      3,
      'http://gcs.test:5030/api/v1/fleet/candidates/hw-101/ignore',
      { reason: 'bench spare' },
    );
  });
});
