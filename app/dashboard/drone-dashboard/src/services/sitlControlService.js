import axios from 'axios';
import { buildGcsUrl, GCS_ROUTES, GCS_ROUTE_KEYS, COMMAND_SUBMIT_TIMEOUT_MS } from './gcsApiService';

const SITL_CONTROL_READ_TIMEOUT_MS = 10000;
const SITL_CONTROL_MUTATION_TIMEOUT_MS = 30000;

function withTimeout(config = {}, timeout) {
  return {
    timeout,
    ...config,
  };
}

export async function getSitlControlPolicy(config = {}) {
  const response = await axios.get(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlPolicy),
    withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
  );
  return response.data;
}

export async function getSitlControlHost(config = {}) {
  const response = await axios.get(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlHost),
    withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
  );
  return response.data;
}

export async function getSitlControlImages(config = {}) {
  const response = await axios.get(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlImages),
    withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
  );
  return response.data;
}

export async function getSitlControlInstances(config = {}) {
  const response = await axios.get(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlInstances),
    withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
  );
  return response.data;
}

export async function createSitlInstance(payload, config = {}) {
  const response = await axios.post(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlInstances),
    payload,
    withTimeout(config, SITL_CONTROL_MUTATION_TIMEOUT_MS),
  );
  return response.data;
}

export async function reconcileSitlFleet(payload, config = {}) {
  const response = await axios.post(
    buildGcsUrl(GCS_ROUTE_KEYS.sitlControlReconcile),
    payload,
    withTimeout(config, SITL_CONTROL_MUTATION_TIMEOUT_MS),
  );
  return response.data;
}

export async function getSitlControlOperations({ limit = 20, ...config } = {}) {
  const response = await axios.get(buildGcsUrl(GCS_ROUTE_KEYS.sitlControlOperations), {
    ...withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
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
    withTimeout(config, COMMAND_SUBMIT_TIMEOUT_MS),
  );
  return response.data;
}

export async function restartSitlInstance(instanceName, config = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.post(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}/restart`),
    {},
    withTimeout(config, SITL_CONTROL_MUTATION_TIMEOUT_MS),
  );
  return response.data;
}

export async function removeSitlInstance(instanceName, config = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.delete(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}`),
    withTimeout(config, SITL_CONTROL_MUTATION_TIMEOUT_MS),
  );
  return response.data;
}

export async function getSitlControlInstanceLogs(instanceName, { tail = 200, ...config } = {}) {
  const encodedName = encodeURIComponent(instanceName);
  const response = await axios.get(
    buildGcsUrl(`${GCS_ROUTES[GCS_ROUTE_KEYS.sitlControlInstances]}/${encodedName}/logs`),
    {
      ...withTimeout(config, SITL_CONTROL_READ_TIMEOUT_MS),
      params: {
        ...(config.params || {}),
        tail,
      },
    },
  );
  return response.data;
}
