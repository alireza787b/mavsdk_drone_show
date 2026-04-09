jest.mock('axios');
jest.mock('./gcsApiService', () => ({
  buildGcsUrl: jest.fn((routeOrPath) => {
    const routeMap = {
      px4ParamsPolicy: '/api/v1/px4-params/policy',
      px4ParamsSnapshots: '/api/v1/px4-params/snapshots',
      px4ParamsPatchJobs: '/api/v1/px4-params/patch-jobs',
    };
    const resolved = routeMap[routeOrPath] || routeOrPath;
    return `http://gcs.test:5000${resolved}`;
  }),
  GCS_ROUTE_KEYS: {
    px4ParamsBase: 'px4ParamsBase',
    px4ParamsPolicy: 'px4ParamsPolicy',
    px4ParamsSnapshots: 'px4ParamsSnapshots',
    px4ParamsPatchJobs: 'px4ParamsPatchJobs',
  },
  GCS_ROUTES: {
    px4ParamsBase: '/api/v1/px4-params',
    px4ParamsPolicy: '/api/v1/px4-params/policy',
    px4ParamsSnapshots: '/api/v1/px4-params/snapshots',
    px4ParamsPatchJobs: '/api/v1/px4-params/patch-jobs',
  },
}));

describe('px4ParamsApiService', () => {
  let service;
  let axios;

  beforeEach(() => {
    jest.resetModules();
    axios = require('axios');
    jest.clearAllMocks();
    service = require('./px4ParamsApiService');
  });

  it('builds urls from the shared px4 params base route', () => {
    expect(service.buildPx4ParamsUrl('/snapshots/snap-1')).toBe('http://gcs.test:5000/api/v1/px4-params/snapshots/snap-1');
  });

  it('loads the px4 params policy from the canonical route', async () => {
    axios.get.mockResolvedValue({ data: { subsystem: 'px4_params' } });

    await service.getPx4ParamPolicy();

    expect(axios.get).toHaveBeenCalledWith('http://gcs.test:5000/api/v1/px4-params/policy');
  });

  it('refreshes snapshots for explicit hw ids', async () => {
    axios.post.mockResolvedValue({ data: { snapshots: [] } });

    await service.refreshPx4ParamSnapshots({ hwIds: ['1', '3'], componentId: 1 });

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/px4-params/snapshots',
      { hw_ids: ['1', '3'], component_id: 1 }
    );
  });

  it('loads snapshot resources through the shared px4 params base url', async () => {
    axios.get.mockResolvedValue({ data: { snapshot: { snapshot_id: 'snap-1' } } });

    await service.getPx4ParamSnapshot('snap/1');
    await service.getPx4ParamSnapshotRows('snap/1');
    await service.getPx4ParamPatchJob('job/1');

    expect(axios.get).toHaveBeenNthCalledWith(1, 'http://gcs.test:5000/api/v1/px4-params/snapshots/snap%2F1');
    expect(axios.get).toHaveBeenNthCalledWith(2, 'http://gcs.test:5000/api/v1/px4-params/snapshots/snap%2F1/rows');
    expect(axios.get).toHaveBeenNthCalledWith(3, 'http://gcs.test:5000/api/v1/px4-params/patch-jobs/job%2F1');
  });

  it('creates patch jobs with canonical snake_case payloads', async () => {
    axios.post.mockResolvedValue({ data: { job_id: 'job-1' } });

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

    expect(axios.post).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/px4-params/patch-jobs',
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
    axios.post.mockResolvedValue({ data: {} });

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

    expect(axios.post).toHaveBeenNthCalledWith(1, 'http://gcs.test:5000/api/v1/px4-params/imports/qgc', { content: '# QGC' });
    expect(axios.post).toHaveBeenNthCalledWith(2, 'http://gcs.test:5000/api/v1/px4-params/imports/mds', { content: '{"entries":[]}' });
    expect(axios.post).toHaveBeenNthCalledWith(
      3,
      'http://gcs.test:5000/api/v1/px4-params/diff',
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
