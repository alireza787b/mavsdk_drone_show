import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { computeOriginResponse } from '../services/gcsApiService';
import OriginModal from './OriginModal';

jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  computeOriginResponse: jest.fn(),
}));

jest.mock('./MapSelector', () => function MockMapSelector({ onSelect }) {
  return (
    <button type="button" onClick={() => onSelect({ lat: 0, lon: 0 })}>
      Pick map origin
    </button>
  );
});

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const configData = [
  { hw_id: 1, pos_id: 7 },
  { hw_id: '2', pos_id: 8 },
];

const readyTelemetry = (hwId, overrides = {}) => ({
  hw_id: String(hwId),
  telemetry_available: true,
  is_armed: false,
  position_lat: 48.8566406,
  position_long: 2.359282,
  position_alt: 50.704,
  global_position_valid: true,
  global_position_age_ms: 250,
  gps_fix_type: 3,
  telemetry_stale_threshold_ms: 15_000,
  ...overrides,
});

const preview = (hwId, posId = Number(hwId), overrides = {}) => ({
  status: 'success',
  origin: {
    lat: 48.8566 + Number(hwId) / 10_000,
    lon: 2.3592,
    alt: 50.704,
    source: 'drone_global_position_msl',
  },
  reference: {
    hw_id: String(hwId),
    pos_id: posId,
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

const defaultProps = () => ({
  isOpen: true,
  onClose: jest.fn(),
  onSubmit: jest.fn(() => Promise.resolve()),
  telemetryData: {
    '1': readyTelemetry(1),
    '2': readyTelemetry(2),
  },
  configData,
  currentOrigin: { lat: null, lon: null, alt: null },
});

const openDroneReference = () => {
  fireEvent.click(screen.getByRole('button', { name: 'Use Drone as Reference' }));
};

const chooseDrone = (hwId) => {
  fireEvent.change(screen.getByRole('combobox', { name: /select drone/i }), {
    target: { value: String(hwId) },
  });
};

describe('OriginModal', () => {
  beforeEach(() => {
    computeOriginResponse.mockReset();
  });

  test('explains that a 3D receiver fix is still waiting for a PX4 map position', async () => {
    const request = deferred();
    computeOriginResponse.mockImplementation(() => request.promise);
    const props = defaultProps();
    props.telemetryData['2'] = readyTelemetry(2, {
      position_lat: 0,
      position_long: 0,
      position_alt: 0,
      global_position_valid: false,
      global_position_age_ms: null,
      gps_raw_valid: true,
      position_unavailable_reason: 'GPS fix present, waiting for valid PX4 global position.',
    });

    render(<OriginModal {...props} />);
    openDroneReference();
    chooseDrone('2');

    await waitFor(() => expect(computeOriginResponse).toHaveBeenCalledWith({ hw_id: '2' }));
    expect(screen.getAllByText(/3D fix · map pending/i)).not.toHaveLength(0);
    expect(screen.getAllByText(/GPS fix present, waiting for valid PX4 global position/i)).not.toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Set Origin' })).toBeDisabled();
  });

  test('previews and atomically saves a drone reference using hardware identity only', async () => {
    computeOriginResponse.mockResolvedValue({ data: preview('2', 8) });
    const props = defaultProps();

    render(<OriginModal {...props} />);
    openDroneReference();
    chooseDrone('2');

    await waitFor(() => expect(screen.getByText('Computed Origin')).toBeInTheDocument());
    expect(computeOriginResponse).toHaveBeenCalledTimes(1);
    expect(computeOriginResponse).toHaveBeenCalledWith({ hw_id: '2' });
    expect(computeOriginResponse.mock.calls[0][0]).not.toHaveProperty('current_lat');
    expect(computeOriginResponse.mock.calls[0][0]).not.toHaveProperty('pos_id');

    fireEvent.click(screen.getByRole('button', { name: 'Set Origin' }));

    await waitFor(() => {
      expect(props.onSubmit).toHaveBeenCalledWith({
        method: 'drone_reference',
        hw_id: '2',
      });
    });
    expect(props.onClose).not.toHaveBeenCalled();
  });

  test('never exposes a stale preview after selection changes while requests are in flight', async () => {
    const firstRequest = deferred();
    const secondRequest = deferred();
    computeOriginResponse
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const props = defaultProps();

    render(<OriginModal {...props} />);
    openDroneReference();
    chooseDrone('1');
    await waitFor(() => expect(computeOriginResponse).toHaveBeenCalledWith({ hw_id: '1' }));
    chooseDrone('2');
    await waitFor(() => expect(computeOriginResponse).toHaveBeenCalledWith({ hw_id: '2' }));

    await act(async () => {
      firstRequest.resolve({ data: preview('1', 7) });
      await Promise.resolve();
    });

    expect(screen.queryByText('Computed Origin')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set Origin' })).toBeDisabled();

    await act(async () => {
      secondRequest.resolve({ data: preview('2', 8) });
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByText('Reference: HW 2, Position 8')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Set Origin' })).toBeEnabled();
  });

  test('keeps the dialog open and reports the server error when persistence fails', async () => {
    computeOriginResponse.mockResolvedValue({ data: preview('2', 8) });
    const props = defaultProps();
    props.onSubmit.mockRejectedValue({
      response: { data: { detail: 'Origin storage is unavailable.' } },
    });

    render(<OriginModal {...props} />);
    openDroneReference();
    chooseDrone('2');
    await waitFor(() => expect(screen.getByText('Computed Origin')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Set Origin' }));

    await waitFor(() => expect(screen.getByText('Origin storage is unavailable.')).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'Set Formation Origin' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set Origin' })).toBeEnabled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  test('preserves legitimate zero manual coordinates and zero MSL altitude', async () => {
    const props = defaultProps();
    props.currentOrigin = { lat: 0, lon: 0, alt: 0 };

    render(<OriginModal {...props} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/coordinates \(lat, lon\)/i)).toHaveValue('0, 0');
      expect(screen.getByLabelText(/altitude msl/i)).toHaveValue(0);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Set Origin' }));

    await waitFor(() => {
      expect(props.onSubmit).toHaveBeenCalledWith({
        method: 'manual',
        lat: 0,
        lon: 0,
        alt: 0,
      });
    });
  });
});
