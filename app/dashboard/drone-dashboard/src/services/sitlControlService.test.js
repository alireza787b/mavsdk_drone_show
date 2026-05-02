import {
  createSitlInstance,
  getSitlControlHost,
  getSitlControlImages,
  getSitlControlInstanceLogs,
  getSitlControlInstances,
  getSitlControlOperation,
  getSitlControlOperations,
  getSitlControlPolicy,
  reconcileSitlFleet,
  releaseSitlImage,
  removeSitlInstance,
  restartSitlInstance,
  runSitlInstanceAction,
} from './sitlControlService';
import {
  deleteGcsResource,
  fetchGcsResource,
  GCS_ROUTE_KEYS,
  postGcsResource,
} from './gcsApiService';

jest.mock('./gcsApiService', () => ({
  COMMAND_SUBMIT_TIMEOUT_MS: 12000,
  deleteGcsResource: jest.fn(),
  fetchGcsResource: jest.fn(),
  postGcsResource: jest.fn(),
  GCS_ROUTES: {
    '/api/v1/system/sitl/instances': '/api/v1/system/sitl/instances',
    '/api/v1/system/sitl/operations': '/api/v1/system/sitl/operations',
  },
  GCS_ROUTE_KEYS: {
    sitlControlPolicy: '/api/v1/system/sitl/policy',
    sitlControlHost: '/api/v1/system/sitl/host',
    sitlControlImages: '/api/v1/system/sitl/images',
    sitlControlImageRelease: '/api/v1/system/sitl/images/release',
    sitlControlInstances: '/api/v1/system/sitl/instances',
    sitlControlInstanceActions: '/api/v1/system/sitl/instances/actions',
    sitlControlReconcile: '/api/v1/system/sitl/reconcile',
    sitlControlOperations: '/api/v1/system/sitl/operations',
  },
}));

describe('sitlControlService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('requests SITL policy through the canonical GCS route', async () => {
    fetchGcsResource.mockResolvedValue({ data: { sim_mode: true } });

    const result = await getSitlControlPolicy();

    expect(fetchGcsResource).toHaveBeenCalledWith(
      GCS_ROUTE_KEYS.sitlControlPolicy,
      { timeout: 10000 },
    );
    expect(result.sim_mode).toBe(true);
  });

  test('requests SITL host, image, and instance inventories', async () => {
    fetchGcsResource.mockResolvedValueOnce({ data: { host: { hostname: 'hetzner' } } });
    fetchGcsResource.mockResolvedValueOnce({ data: { images: [{ image_id: 'sha256:1' }] } });
    fetchGcsResource.mockResolvedValueOnce({ data: { instances: [{ name: 'drone-1' }] } });

    const host = await getSitlControlHost();
    const images = await getSitlControlImages();
    const instances = await getSitlControlInstances();

    expect(host.host.hostname).toBe('hetzner');
    expect(images.images[0].image_id).toBe('sha256:1');
    expect(instances.instances[0].name).toBe('drone-1');
  });

  test('encodes container name and tail when requesting instance logs', async () => {
    fetchGcsResource.mockResolvedValue({ data: { lines: ['boot', 'ready'] } });

    const result = await getSitlControlInstanceLogs('drone/1', { tail: 80 });

    expect(fetchGcsResource).toHaveBeenCalledWith(
      '/api/v1/system/sitl/instances/drone%2F1/logs',
      expect.objectContaining({
        timeout: 10000,
        params: { tail: 80 },
      }),
    );
    expect(result.lines).toEqual(['boot', 'ready']);
  });

  test('posts reconcile payload and encodes instance lifecycle routes', async () => {
    postGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-1' } });
    postGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-create' } });
    fetchGcsResource.mockResolvedValueOnce({ data: { operations: [] } });
    fetchGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-1' } });
    postGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-2' } });
    postGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-4' } });
    postGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-5' } });
    deleteGcsResource.mockResolvedValueOnce({ data: { operation_id: 'sitl-op-3' } });

    const reconcile = await reconcileSitlFleet({ target_count: 3 });
    const create = await createSitlInstance({ instance_id: 6 });
    const operations = await getSitlControlOperations({ limit: 5 });
    const operation = await getSitlControlOperation('sitl/op');
    const restart = await restartSitlInstance('drone/1');
    const batch = await runSitlInstanceAction({ action: 'restart', instance_names: ['drone-1'] });
    const release = await releaseSitlImage({ image_repo: 'mavsdk-drone-show-sitl', version_tag: 'release-demo' });
    const remove = await removeSitlInstance('drone/1');

    expect(postGcsResource).toHaveBeenNthCalledWith(
      1,
      GCS_ROUTE_KEYS.sitlControlReconcile,
      { target_count: 3 },
      { timeout: 30000 },
    );
    expect(postGcsResource).toHaveBeenNthCalledWith(
      2,
      GCS_ROUTE_KEYS.sitlControlInstances,
      { instance_id: 6 },
      { timeout: 30000 },
    );
    expect(fetchGcsResource).toHaveBeenNthCalledWith(
      1,
      GCS_ROUTE_KEYS.sitlControlOperations,
      expect.objectContaining({ params: { limit: 5 } }),
    );
    expect(fetchGcsResource).toHaveBeenNthCalledWith(
      2,
      '/api/v1/system/sitl/operations/sitl%2Fop',
      { timeout: 12000 },
    );
    expect(postGcsResource).toHaveBeenNthCalledWith(
      3,
      '/api/v1/system/sitl/instances/drone%2F1/restart',
      {},
      { timeout: 30000 },
    );
    expect(postGcsResource).toHaveBeenNthCalledWith(
      4,
      GCS_ROUTE_KEYS.sitlControlInstanceActions,
      { action: 'restart', instance_names: ['drone-1'] },
      { timeout: 30000 },
    );
    expect(postGcsResource).toHaveBeenNthCalledWith(
      5,
      GCS_ROUTE_KEYS.sitlControlImageRelease,
      { image_repo: 'mavsdk-drone-show-sitl', version_tag: 'release-demo' },
      { timeout: 30000 },
    );
    expect(deleteGcsResource).toHaveBeenCalledWith(
      '/api/v1/system/sitl/instances/drone%2F1',
      { timeout: 30000 },
    );
    expect(reconcile.operation_id).toBe('sitl-op-1');
    expect(create.operation_id).toBe('sitl-op-create');
    expect(operations.operations).toEqual([]);
    expect(operation.operation_id).toBe('sitl-op-1');
    expect(restart.operation_id).toBe('sitl-op-2');
    expect(batch.operation_id).toBe('sitl-op-4');
    expect(release.operation_id).toBe('sitl-op-5');
    expect(remove.operation_id).toBe('sitl-op-3');
  });
});
