import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import DroneActions from './DroneActions';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';

describe('DroneActions', () => {
  test('sends takeoff immediately by default', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove}
        targetCount={3}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /take off/i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      missionType: String(DRONE_ACTION_TYPES.TAKE_OFF),
      triggerTime: '0',
      takeoff_altitude: 10,
      uiMeta: expect.objectContaining({
        triggerSummary: 'Immediate on acceptance',
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Execution policy',
            value: 'Launch begins on acceptance and retries PX4 armability briefly before failing.',
          }),
        ]),
      }),
    }));
  });

  test('allows scheduled takeoff while leaving maintenance actions immediate', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove}
        targetCount={3}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByText(/execution timing/i));
    fireEvent.click(screen.getByRole('button', { name: 'Delay' }));
    fireEvent.click(screen.getByRole('button', { name: '+30s' }));
    fireEvent.click(screen.getByRole('button', { name: /take off/i }));

    expect(onSendCommand).toHaveBeenNthCalledWith(1, expect.objectContaining({
      missionType: String(DRONE_ACTION_TYPES.TAKE_OFF),
      triggerTime: '1700000030',
      uiMeta: expect.objectContaining({
        triggerSummary: expect.stringMatching(/Executes in 30s/),
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Execution policy',
            value: 'Launch waits for the trigger, then retries PX4 armability briefly before failing.',
          }),
        ]),
      }),
    }));

    fireEvent.click(screen.getByRole('button', { name: /update code/i }));

    expect(onSendCommand).toHaveBeenNthCalledWith(2, expect.objectContaining({
      missionType: String(DRONE_ACTION_TYPES.UPDATE_CODE),
      triggerTime: '0',
      uiMeta: expect.objectContaining({
        triggerSummary: 'Immediate on acceptance',
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Execution policy',
            value: 'Immediate only. This action is not queued behind a future trigger.',
          }),
        ]),
      }),
    }));
  });

  test('treats hover test as a strict synchronized rehearsal in scheduled mode', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove}
        targetCount={3}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByText(/execution timing/i));
    fireEvent.click(screen.getByRole('button', { name: 'Delay' }));
    fireEvent.click(screen.getByRole('button', { name: '+30s' }));
    fireEvent.click(screen.getByRole('button', { name: /hover test/i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      missionType: String(DRONE_ACTION_TYPES.HOVER_TEST),
      triggerTime: '1700000030',
      uiMeta: expect.objectContaining({
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Execution policy',
            value: expect.stringMatching(/queue for the shared trigger.*abort instead of joining late/i),
          }),
        ]),
      }),
    }));
  });

  test('routes precision move to the dedicated request callback instead of direct dispatch', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove}
        targetCount={3}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /precision move/i }));

    expect(onRequestPrecisionMove).toHaveBeenCalledTimes(1);
    expect(onSendCommand).not.toHaveBeenCalled();
  });
});
