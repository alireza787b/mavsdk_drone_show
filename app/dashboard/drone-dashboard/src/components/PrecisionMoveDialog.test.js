import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import PrecisionMoveDialog from './PrecisionMoveDialog';
import { getPrecisionMovePolicyResponse } from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  getPrecisionMovePolicyResponse: jest.fn(),
}));

describe('PrecisionMoveDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getPrecisionMovePolicyResponse.mockResolvedValue({
      data: {
        action: 'precision_move',
        defaults: {
          speed_m_s: 1,
          position_tolerance_m: 0.15,
          yaw_tolerance_deg: 5,
          settle_time_sec: 1,
          timeout_sec: 30,
        },
        limits: {
          max_translation_m: 100,
          max_speed_m_s: 5,
          min_position_tolerance_m: 0.05,
          max_timeout_sec: 180,
          min_airborne_altitude_m: 0.3,
          control_rate_hz: 10,
        },
        execution: {
          supported_frames: ['body', 'ned'],
          supported_yaw_modes: ['hold_current', 'relative_delta', 'absolute_heading'],
          hold_mode: 'px4_hold',
          immediate_only: true,
          requires_airborne: true,
          requires_local_position: true,
        },
      },
    });
  });

  function renderDialog(overrides = {}) {
    return render(
      <PrecisionMoveDialog
        isOpen
        targetLabel="2 selected drones"
        targetDescriptor="Selected drones: 1, 2"
        targetCount={2}
        liveMonitor={{
          commandLabel: 'Precision Move',
          isTerminal: false,
          acks: { accepted: 2, expected: 2 },
          progress: {
            label: 'Execution in progress',
            message: 'Move is active on 2 drone(s).',
            stage: 'executing',
            active: 2,
            completed: 0,
          },
        }}
        submitting={false}
        onClose={jest.fn()}
        onEditTargetScope={jest.fn()}
        onSubmit={jest.fn()}
        onSubmitHold={jest.fn()}
        {...overrides}
      />
    );
  }

  it('loads runtime defaults and exposes manual tuning when expanded', async () => {
    await act(async () => {
      renderDialog();
    });

    await waitFor(() => expect(getPrecisionMovePolicyResponse).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('Default speed')).toBeInTheDocument());

    expect(screen.getByText('Live Command Status')).toBeInTheDocument();
    expect(screen.getByText('Default speed')).toBeInTheDocument();

    fireEvent.click(screen.getByText(/manual vector and heading/i));

    expect(screen.getByLabelText(/forward \(\+\) \/ back \(-\)/i)).toBeInTheDocument();
  });

  it('returns the operator to the shared scope editor when requested', () => {
    const onEditTargetScope = jest.fn();
    renderDialog({ onEditTargetScope });

    fireEvent.click(screen.getByRole('button', { name: /edit scope/i }));

    expect(onEditTargetScope).toHaveBeenCalledTimes(1);
  });
});
