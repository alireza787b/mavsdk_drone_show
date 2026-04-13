import axios from 'axios';
import { buildGcsUrl, GCS_ROUTES, GCS_ROUTE_KEYS } from './gcsApiService';

export async function getSitlControlPolicy(config = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlPolicy), config);
  return response.data;
}

export async function getSitlControlHost(config = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlHost), config);
  return response.data;
}

export async function getSitlControlImages(config = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlImages), config);
  return response.data;
}

export async function getSitlControlInstances(config = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlInstances), config);
  return response.data;
}

export async function reconcileSitlFleet(payload, config = {}) {
  const response = await axios.post(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlReconcile), payload, config);
  return response.data;
}

export async function getSitlControlOperations({ limit = 20, ...config } = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlOperations), {
    ...config,
    params: {
      ...(config.params || {}),
      limit,
    },
  });
  return response.data;
}

export async function getSitlControlOperation(operationId, config = {}) {
  const encodedId = encodeURIComponent(operationId);
  const response = await axios.get(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlOperations]}/${encodedId}`),
    config,
  );
  return response.data;
}

export async function restartSitlInstance(instanceName, config = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.post(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}/restart`),
    {},
    config,
  );
  return response.data;
}

export async function removeSitlInstance(instanceName, config = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.delete(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}`),
    config,
  );
  return response.data;
}

export async function getSitlControlInstanceLogs(instanceName, { tail = 200, ...config } = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.get(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}/logs`),
    {
      ...config,
      params: {
        ...(config.params || {}),
        tail,
      },
    },
  );
  return response.data;
}
