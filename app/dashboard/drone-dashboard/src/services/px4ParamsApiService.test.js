jest.mock('./gcsApiService', () => ({
  buildGcsUrl: jest.fn((routeOrPath) => {
    const routeMap = {
      px4ParamsPolicy: '/api/v1/px4-params/policy',
      px4ParamsProfiles: '/api/v1/px4-params/profiles',
      px4ParamsSnapshots: '/api/v1/px4-params/snapshots',
      px4ParamsPatchJobs: '/api/v1/px4-params/patch-jobs',
    };
    const resolved = routeMap[routeOrPath] || routeOrPath;
    return `http://gcs.test:5030${resolved}`;
  }),
  fetchGcsResource: jest.fn(),
  postGcsResource: jest.fn(),
  GCS_ROUTE_KEYS: {
      px4ParamsBase: 'px4ParamsBase',
      px4ParamsPolicy: 'px4ParamsPolicy',
      px4ParamsProfiles: 'px4ParamsProfiles',
      px4ParamsSnapshots: 'px4ParamsSnapshots',
      px4ParamsPatchJobs: 'px4ParamsPatchJobs',
  },
  GCS_ROUTES: {
    px4ParamsBase: '/api/v1/px4-params',
    px4ParamsPolicy: '/api/v1/px4-params/policy',
    px4ParamsProfiles: '/api/v1/px4-params/profiles',
    px4ParamsSnapshots: '/api/v1/px4-params/snapshots',
    px4ParamsPatchJobs: '/api/v1/px4-params/patch-jobs',
  },
}));

describe('px4ParamsApiService', () => {
  let service;
  let gcsApi;

  beforeEach(() => {
    jest.resetModules();
    gcsApi = require('./gcsApiService');
    jest.clearAllMocks();
    service = require('./px4ParamsApiService');
  });

  it('builds urls from the shared px4 params base route', () => {
    expect(service.buildPx4ParamsUrl('/snapshots/snap-1')).toBe('http://gcs.test:5030/api/v1/px4-params/snapshots/snap-1');
  });

  it('loads the px4 params policy from the canonical route', async () => {
    gcsApi.fetchGcsResource.mockResolvedValue({ data: { subsystem: 'px4_params' } });

    await service.getPx4ParamPolicy();

    expect(gcsApi.fetchGcsResource).toHaveBeenCalledWith('px4ParamsPolicy');
  });

  it('loads repo-backed profile resources from canonical routes', async () => {
    gcsApi.fetchGcsResource.mockResolvedValue({ data: { profiles: [] } });

    await service.listPx4ParamProfiles();
    await service.getPx4ParamProfile('fleet/guard');

    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(1, 'px4ParamsProfiles');
    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(2, 'http://gcs.test:5030/api/v1/px4-params/profiles/fleet%2Fguard');
  });

  it('refreshes snapshots for explicit hw ids', async () => {
    gcsApi.postGcsResource.mockResolvedValue({ data: { snapshots: [] } });

    await service.refreshPx4ParamSnapshots({ hwIds: ['1', '3'], componentId: 1 });

    expect(gcsApi.postGcsResource).toHaveBeenCalledWith(
      'px4ParamsSnapshots',
      { hw_ids: ['1', '3'], component_id: 1 }
    );
  });

  it('loads snapshot resources through the shared px4 params base url', async () => {
    gcsApi.fetchGcsResource.mockResolvedValue({ data: { snapshot: { snapshot_id: 'snap-1' } } });

    await service.getPx4ParamSnapshot('snap/1');
    await service.getPx4ParamSnapshotRows('snap/1');
    await service.getPx4ParamPatchJob('job/1');

    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(1, 'http://gcs.test:5030/api/v1/px4-params/snapshots/snap%2F1');
    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(2, 'http://gcs.test:5030/api/v1/px4-params/snapshots/snap%2F1/rows');
    expect(gcsApi.fetchGcsResource).toHaveBeenNthCalledWith(3, 'http://gcs.test:5030/api/v1/px4-params/patch-jobs/job%2F1');
  });

  it('creates patch jobs with canonical snake_case payloads', async () => {
    gcsApi.postGcsResource.mockResolvedValue({ data: { job_id: 'job-1' } });

    await service.createPx4ParamPatchJob({
      hwIds: ['7'],
      source: 'manual',
      verifyReadback: false,
      entries: [
        {
          component_id: 1,
          name: 'MPC_XY_VEL_MAX',
          value_type: 'float',
          value: 8.5,
        },
      ],
    });

    expect(gcsApi.postGcsResource).toHaveBeenCalledWith(
      'px4ParamsPatchJobs',
      {
        hw_ids: ['7'],
        source: 'manual',
        verify_readback: false,
        entries: [
          {
            component_id: 1,
            name: 'MPC_XY_VEL_MAX',
            value_type: 'float',
            value: 8.5,
          },
        ],
      }
    );
  });

  it('parses imports and diff requests through canonical px4 params routes', async () => {
    gcsApi.postGcsResource.mockResolvedValue({ data: {} });

    await service.importQgcParameterFile('# QGC');
    await service.importMdsPatch('{"entries":[]}');
    await service.diffPx4ParamSnapshot({
      snapshotId: 'snap-1',
      desiredEntries: [
        {
          component_id: 1,
          name: 'MPC_XY_VEL_MAX',
          value_type: 'float',
          value: 12.0,
        },
      ],
      includeUnchanged: true,
    });

    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(1, 'http://gcs.test:5030/api/v1/px4-params/imports/qgc', { content: '# QGC' });
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(2, 'http://gcs.test:5030/api/v1/px4-params/imports/mds', { content: '{"entries":[]}' });
    expect(gcsApi.postGcsResource).toHaveBeenNthCalledWith(
      3,
      'http://gcs.test:5030/api/v1/px4-params/diff',
      {
        snapshot_id: 'snap-1',
        desired_entries: [
          {
            component_id: 1,
            name: 'MPC_XY_VEL_MAX',
            value_type: 'float',
            value: 12.0,
          },
        ],
        include_unchanged: true,
      }
    );
  });
});
