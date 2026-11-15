import React, { StrictMode } from 'react';
import { act, render, screen, cleanup } from '@testing-library/react';
import { ObservationProvider, useObservationResource } from './ObservationContext';
import useFetch from '../hooks/useFetch';
import { getFleetConfigResponse, getFleetTelemetryResponse, fetchGcsResource, GCS_ROUTE_KEYS } from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({ ...jest.requireActual('../services/gcsApiService'),
  getFleetConfigResponse: jest.fn(), getFleetTelemetryResponse: jest.fn(), fetchGcsResource: jest.fn() }));
const flush = async () => { await act(async () => { for (let n = 0; n < 5; n += 1) await Promise.resolve(); }); };
beforeEach(() => {
  jest.useFakeTimers(); jest.clearAllMocks();
  getFleetConfigResponse.mockResolvedValue({ data: [{ hw_id: '1' }] });
  getFleetTelemetryResponse.mockResolvedValue({ data: { telemetry: { 1: { hw_id: '1' } } } });
  fetchGcsResource.mockResolvedValue({ data: {} });
});
afterEach(() => { cleanup(); jest.useRealTimers(); });

function Reader({ name }) {
  const resource = useObservationResource(name);
  return <span data-testid={name}>{JSON.stringify(resource.response?.data)}</span>;
}
test('shell and page readers share one owner; route removal leaves monitoring alive', async () => {
  const View = ({ page }) => <ObservationProvider><Reader name="telemetry" />{page && <Reader name="telemetry" />}</ObservationProvider>;
  const view = render(<View page />); await flush();
  expect(getFleetTelemetryResponse).toHaveBeenCalledTimes(1);
  view.rerender(<View page={false} />);
  await act(async () => { jest.advanceTimersByTime(1000); });
  expect(getFleetTelemetryResponse).toHaveBeenCalledTimes(2);
  view.unmount();
  expect(jest.getTimerCount()).toBe(0);
});
test('legacy hook is an adapter to same resource, not another polling engine', async () => {
  function Adapter() { const { data } = useFetch(GCS_ROUTE_KEYS.fleetConfig, 100); return <b>{data?.length ?? 0}</b>; }
  render(<ObservationProvider><Reader name="config" /><Adapter /></ObservationProvider>); await flush();
  expect(getFleetConfigResponse).toHaveBeenCalledTimes(1);
  expect(screen.getByText('1')).toBeInTheDocument();
});
test('new authenticated provider cannot inherit a previous session cache or late response', async () => {
  let resolve;
  getFleetConfigResponse.mockReturnValueOnce(new Promise(yes => { resolve = yes; }));
  const view = render(<ObservationProvider key="old"><Reader name="config" /></ObservationProvider>);
  const signal = getFleetConfigResponse.mock.calls[0][0].signal;
  view.rerender(<ObservationProvider key="new"><Reader name="config" /></ObservationProvider>); await flush();
  expect(signal.aborted).toBe(true);
  await act(async () => resolve({ data: [{ hw_id: 'wrong-session' }] }));
  expect(screen.getByTestId('config')).not.toHaveTextContent('wrong-session');
});
test('StrictMode retains one owner and nested mode scope reuses runtime acquisition', async () => {
  render(<StrictMode><ObservationProvider><Reader name="runtime" /><ObservationProvider><Reader name="runtime" /></ObservationProvider></ObservationProvider></StrictMode>);
  await flush();
  // StrictMode deliberately aborts/restarts the first mount. Both readers
  // share a single request within each mounted generation.
  expect(fetchGcsResource.mock.calls.length).toBeLessThanOrEqual(2);
  expect(fetchGcsResource.mock.calls.every(([route]) => route === GCS_ROUTE_KEYS.systemRuntimeStatus)).toBe(true);
});
