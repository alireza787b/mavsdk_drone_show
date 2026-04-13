import axios from 'axios';
import {
  getSitlControlHost,
  getSitlControlImages,
  getSitlControlInstanceLogs,
  getSitlControlInstances,
  getSitlControlOperation,
  getSitlControlOperations,
  getSitlControlPolicy,
  reconcileSitlFleet,
  removeSitlInstance,
  restartSitlInstance,
} from './sitlControlService';
import { buildGcsUrl, GCS_ROUTE_KEYS } from './gcsApiService';

jest.mock('axios');
jest.mock('./gcsApiService', () => ({
  buildGcsUrl: jest.fn((path) => `http://gcs.test:5000${path}`),
  COMMAND_SUBMIT_TIMEOUT_MS: 12000,
  GCS_ROUTES: {
    '/api/v1/system/sitl/instances': '/api/v1/system/sitl/instances',
    '/api/v1/system/sitl/operations': '/api/v1/system/sitl/operations',
  },
  GCS_ROUTE_KEYS: {
    sitlControlPolicy: '/api/v1/system/sitl/policy',
    sitlControlHost: '/api/v1/system/sitl/host',
    sitlControlImages: '/api/v1/system/sitl/images',
    sitlControlInstances: '/api/v1/system/sitl/instances',
    sitlControlReconcile: '/api/v1/system/sitl/reconcile',
    sitlControlOperations: '/api/v1/system/sitl/operations',
  },
}));

describe('sitlControlService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    buildGcsUrl.mockImplementation((path) => `http://gcs.test:5000${path}`);
  });

  test('requests SITL policy through the canonical GCS route', async () => {
    axios.get.mockResolvedValue({ data: { sim_mode: true } });

    const result = await getSitlControlPolicy();

    expect(buildGcsUrl).toHaveBeenCalledWith(GCS_ROUTE_KEYS.sitlControlPolicy);
    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/sitl/policy',
      { timeout: 10000 },
    );
    expect(result.sim_mode).toBe(true);
  });

  test('requests SITL host, image, and instance inventories', async () => {
    axios.get.mockResolvedValueOnce({ data: { host: { hostname: 'hetzner' } } });
    axios.get.mockResolvedValueOnce({ data: { images: [{ image_id: 'sha256:1' }] } });
    axios.get.mockResolvedValueOnce({ data: { instances: [{ name: 'drone-1' }] } });

    const host = await getSitlControlHost();
    const images = await getSitlControlImages();
    const instances = await getSitlControlInstances();

    expect(host.host.hostname).toBe('hetzner');
    expect(images.images[0].image_id).toBe('sha256:1');
    expect(instances.instances[0].name).toBe('drone-1');
  });

  test('encodes container name and tail when requesting instance logs', async () => {
    axios.get.mockResolvedValue({ data: { lines: ['boot', 'ready'] } });

    const result = await getSitlControlInstanceLogs('drone/1', { tail: 80 });

    expect(buildGcsUrl).toHaveBeenCalledWith('/api/v1/system/sitl/instances/drone%2F1/logs');
    expect(axios.get).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/sitl/instances/drone%2F1/logs',
      expect.objectContaining({
        timeout: 10000,
        params: { tail: 80 },
      }),
    );
    expect(result.lines).toEqual(['boot', 'ready']);
  });

  test('posts reconcile payload and encodes instance lifecycle routes', async () => {
    axios.post.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-1' } });
    axios.get.mockResolvedValueOnce({ data: { operations: [] } });
    axios.get.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-1' } });
    axios.post.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-2' } });
    axios.delete.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-3' } });

    const reconcile = await reconcileSitlFleet({ target_count: 3 });
    const operations = await getSitlControlOperations({ limit: 5 });
    const operation = await getSitlControlOperation('sitl/op');
    const restart = await restartSitlInstance('drone/1');
    const remove = await removeSitlInstance('drone/1');

    expect(axios.post).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5000/api/v1/system/sitl/reconcile',
      { target_count: 3 },
      { timeout: 30000 },
    );
    expect(axios.get).toHaveBeenNthCalledWith(
      1,
      'http://gcs.test:5000/api/v1/system/sitl/operations',
      expect.objectContaining({ params: { limit: 5 } }),
    );
    expect(axios.get).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5000/api/v1/system/sitl/operations/sitl%2Fop',
      { timeout: 12000 },
    );
    expect(axios.post).toHaveBeenNthCalledWith(
      2,
      'http://gcs.test:5000/api/v1/system/sitl/instances/drone%2F1/restart',
      {},
      { timeout: 30000 },
    );
    expect(axios.delete).toHaveBeenCalledWith(
      'http://gcs.test:5000/api/v1/system/sitl/instances/drone%2F1',
      { timeout: 30000 },
    );
    expect(reconcile.operation_id).toBe('sitl-op-1');
    expect(operations.operations).toEqual([]);
    expect(operation.operation_id).toBe('sitl-op-1');
    expect(restart.operation_id).toBe('sitl-op-2');
    expect(remove.operation_id).toBe('sitl-op-3');
  });
});
