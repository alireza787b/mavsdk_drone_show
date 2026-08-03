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

    fireEvent.click(screen.getByRole('button', { name: /^take off\./i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.TAKE_OFF,
      trigger_time: 0,
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
    fireEvent.click(screen.getByRole('button', { name: /^take off\./i }));

    expect(onSendCommand).toHaveBeenNthCalledWith(1, expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.TAKE_OFF,
      trigger_time: 1700000030,
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

    fireEvent.click(screen.getByRole('button', { name: /reboot companion computer/i }));

    expect(onSendCommand).toHaveBeenNthCalledWith(2, expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.REBOOT_SYS,
      trigger_time: 0,
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

  test('labels automated hover as a flight and treats it as a strict synchronized rehearsal', () => {
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
    fireEvent.click(screen.getByRole('button', { name: /automated hover flight/i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.HOVER_TEST,
      trigger_time: 1700000030,
      uiMeta: expect.objectContaining({
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Flight behavior',
            value: expect.stringMatching(/launches.*not a Hold command/i),
          }),
          expect.objectContaining({
            label: 'Execution policy',
            value: expect.stringMatching(/queue for the shared trigger.*abort instead of joining late/i),
          }),
        ]),
      }),
    }));
  });

  test('makes the physical motor-arm behavior explicit for the ground test', () => {
    const onSendCommand = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={jest.fn()}
        targetCount={2}
        runtimeMode="real"
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /arm\/disarm ground test/i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.TEST,
      ground_test_safety: {
        mode: 'operator_acknowledged',
        props_removed: true,
        airframe_secured: true,
        area_clear: true,
      },
      uiMeta: expect.objectContaining({
        operatorLabel: 'Arm/Disarm Ground Test',
        confirmationMessage: expect.stringMatching(/confirm only after all propellers are removed/i),
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Ground-test safety',
            value: expect.stringMatching(/motors will arm.*propellers are removed/i),
          }),
        ]),
      }),
    }));
  });

  test('uses an explicit not-applicable acknowledgement only in SITL mode', () => {
    const onSendCommand = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={jest.fn()}
        targetCount={1}
        runtimeMode="sitl"
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /arm\/disarm ground test/i }));

    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      ground_test_safety: { mode: 'sitl_not_applicable' },
      uiMeta: expect.objectContaining({
        confirmationMessage: expect.stringMatching(/sitl.*simulation-only/i),
      }),
    }));
  });

  test('blocks the motor-arm test when runtime truth is unavailable', () => {
    const onSendCommand = jest.fn();

    render(
      <DroneActions
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={jest.fn()}
        targetCount={1}
        runtimeMode="unknown"
      />
    );

    const button = screen.getByRole('button', { name: /arm\/disarm ground test/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onSendCommand).not.toHaveBeenCalled();
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
