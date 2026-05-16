import { getElevation } from './utilities';

jest.mock('../config/apiConfig', () => ({
  getBackendURL: jest.fn(() => 'http://gcs.test:5030'),
}));

jest.mock('../services/gcsApiService', () => ({
  buildGcsUrl: jest.fn(() => 'http://gcs.test:5030/api/elevation'),
  GCS_ROUTE_KEYS: {
    elevation: 'elevation',
    fleetTelemetry: 'fleetTelemetry',
    gitStatus: 'gitStatus',
    customShowImage: 'customShowImage',
  },
}));

describe('utilities elevation helpers', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('preserves sea-level 0m elevation as a valid value', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{ elevation: 0 }] }),
    });

    await expect(getElevation(25.0001, 121.0001)).resolves.toBe(0);
  });

  it('returns null when the provider omits elevation data', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: [{}] }),
    });

    await expect(getElevation(26.0001, 122.0001)).resolves.toBeNull();
  });
});
