import { act, renderHook, waitFor } from '@testing-library/react';

import { computeOriginResponse } from '../services/gcsApiService';
import useComputeOrigin from './useComputeOrigin';

jest.mock('../services/gcsApiService', () => ({
  computeOriginResponse: jest.fn(),
}));

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const preview = (hwId, overrides = {}) => ({
  status: 'success',
  origin: {
    lat: 48.8566,
    lon: 2.3592,
    alt: 50.7,
    source: 'drone_global_position_msl',
  },
  reference: {
    hw_id: String(hwId),
    pos_id: Number(hwId),
    latitude: 48.8566406,
    longitude: 2.359282,
    altitude_msl: 50.704,
    position_source: 'global_position_int',
    position_timestamp_ms: 1_700_000_000_000,
    position_age_ms: 250,
    gps_fix_type: 3,
  },
  intended_offset: { north_m: -5, east_m: -2.5 },
  ...overrides,
});

describe('useComputeOrigin', () => {
  beforeEach(() => {
    computeOriginResponse.mockReset();
  });

  test('sends hardware identity only and stores the matching server-authoritative preview', async () => {
    computeOriginResponse.mockResolvedValue({ data: preview('2') });
    const { result } = renderHook(() => useComputeOrigin());

    await act(async () => {
      await result.current.computeOrigin({ hw_id: '2', current_lat: 1, pos_id: 99 });
    });

    expect(computeOriginResponse).toHaveBeenCalledWith({ hw_id: '2' });
    expect(result.current.origin).toEqual(preview('2'));
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  test('clears an old preview immediately and surfaces structured FastAPI detail on failure', async () => {
    computeOriginResponse.mockResolvedValueOnce({ data: preview('1') });
    const nextRequest = deferred();
    computeOriginResponse.mockImplementationOnce(() => nextRequest.promise);
    const { result } = renderHook(() => useComputeOrigin());

    await act(async () => {
      await result.current.computeOrigin({ hw_id: '1' });
    });
    expect(result.current.origin).toEqual(preview('1'));

    let pending;
    act(() => {
      pending = result.current.computeOrigin({ hw_id: '2' });
    });

    expect(result.current.origin).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => {
      nextRequest.reject({
        response: {
          data: {
            detail: {
              code: 'origin_reference_position_unavailable',
              message: 'GPS receiver has a 3D fix, but PX4 global position is not available.',
            },
          },
        },
      });
      await pending;
    });

    expect(result.current.origin).toBeNull();
    expect(result.current.error).toBe(
      'GPS receiver has a 3D fix, but PX4 global position is not available.'
    );
    expect(result.current.loading).toBe(false);
  });

  test('ignores an older response that completes after a newer drone selection', async () => {
    const firstRequest = deferred();
    const secondRequest = deferred();
    computeOriginResponse
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const { result } = renderHook(() => useComputeOrigin());

    let firstPending;
    let secondPending;
    act(() => {
      firstPending = result.current.computeOrigin({ hw_id: '1' });
    });
    act(() => {
      secondPending = result.current.computeOrigin({ hw_id: '2' });
    });

    await act(async () => {
      secondRequest.resolve({ data: preview('2') });
      await secondPending;
    });

    expect(result.current.origin).toEqual(preview('2'));

    await act(async () => {
      firstRequest.resolve({ data: preview('1') });
      await firstPending;
    });

    expect(result.current.origin).toEqual(preview('2'));
    expect(result.current.loading).toBe(false);
  });

  test('reset invalidates an in-flight request and clears all visible state', async () => {
    const request = deferred();
    computeOriginResponse.mockImplementation(() => request.promise);
    const { result } = renderHook(() => useComputeOrigin());

    let pending;
    act(() => {
      pending = result.current.computeOrigin({ hw_id: '2' });
    });
    expect(result.current.loading).toBe(true);

    act(() => {
      result.current.resetOrigin();
    });
    expect(result.current).toMatchObject({ origin: null, error: null, loading: false });

    await act(async () => {
      request.resolve({ data: preview('2') });
      await pending;
    });

    await waitFor(() => {
      expect(result.current).toMatchObject({ origin: null, error: null, loading: false });
    });
  });
});
