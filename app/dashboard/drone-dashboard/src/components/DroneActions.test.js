import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import DroneActions from './DroneActions';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';

describe('DroneActions', () => {
  test('sends takeoff immediately by default', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();

    render(
      <DroneActions
        includeFlightControls
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
        includeFlightControls
        actionTypes={DRONE_ACTION_TYPES}
        onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove}
        targetCount={3}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByText('Advanced timing'));
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

    fireEvent.click(screen.getByText('Advanced timing'));
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

  test('makes the physical motor-arm behavior explicit without fabricating acknowledgements before review', () => {
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
      uiMeta: expect.objectContaining({
        operatorLabel: 'Arm/Disarm Ground Test',
        confirmationMessage: expect.stringMatching(/confirm only after all propellers are removed/i),
        details: expect.arrayContaining([
          expect.objectContaining({
            label: 'Ground-test safety',
            value: expect.stringMatching(/motors will arm.*confirm propellers removed/i),
          }),
        ]),
      }),
    }));
    expect(onSendCommand.mock.calls[0][0]).not.toHaveProperty('ground_test_safety');
  });

  test('labels SITL motor-arm intent and leaves acknowledgement construction to the shared review', () => {
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
      uiMeta: expect.objectContaining({
        confirmationMessage: expect.stringMatching(/sitl.*simulation-only/i),
      }),
    }));
    expect(onSendCommand.mock.calls[0][0]).not.toHaveProperty('ground_test_safety');
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
        canPrecisionMove
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

  test('More does not duplicate the four primary controls and timing starts collapsed', () => {
    const { container } = render(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={2} onSendCommand={jest.fn()} />);
    ['Take Off', 'Hold Position', 'Land', 'Return to Launch'].forEach((name) => {
      expect(screen.queryByRole('button', { name: new RegExp(`^${name}\\.`) })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /automated hover flight/i })).toBeInTheDocument();
    expect(container.querySelector('details')).not.toHaveAttribute('open');
    expect(screen.getByRole('button', { name: 'Delay' }).closest('details')).not.toHaveAttribute('open');
  });

  test('Move is unavailable unless the caller explicitly provides current-airborne capability', () => {
    const onRequestPrecisionMove = jest.fn();
    const onSendCommand = jest.fn();
    const view = render(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={2} onSendCommand={onSendCommand}
      onRequestPrecisionMove={onRequestPrecisionMove} />);
    const button = screen.getByRole('button', { name: /precision move/i });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Requires current airborne telemetry');
    fireEvent.click(button);
    expect(onRequestPrecisionMove).not.toHaveBeenCalled();
    view.rerender(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={2} onSendCommand={onSendCommand}
      onRequestPrecisionMove={onRequestPrecisionMove} canPrecisionMove />);
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onRequestPrecisionMove).toHaveBeenCalledTimes(1);
    expect(onSendCommand).not.toHaveBeenCalled();
  });

  test('Cancel mission uses NONE immediately even with delayed test timing', () => {
    const onSendCommand = jest.fn();
    render(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={2} onSendCommand={onSendCommand}
      referenceNowMs={1_700_000_000_000} />);
    fireEvent.click(screen.getByText('Advanced timing'));
    fireEvent.click(screen.getByRole('button', { name: 'Delay' }));
    fireEvent.click(screen.getByRole('button', { name: /cancel mission/i }));
    expect(onSendCommand).toHaveBeenCalledWith(expect.objectContaining({
      mission_type: DRONE_MISSION_TYPES.NONE,
      trigger_time: 0,
      uiMeta: expect.objectContaining({ actionKey: 'NONE', operatorLabel: 'Cancel Mission', triggerSummary: 'Immediate on acceptance' }),
    }));
    expect(onSendCommand.mock.calls[0][0]).not.toHaveProperty('target_drone_ids');
  });

  test('ground LED testing preserves scheduled dispatch and motor stop remains immediate', () => {
    const onSendCommand = jest.fn();
    render(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={2} onSendCommand={onSendCommand}
      referenceNowMs={1_700_000_000_000} />);
    fireEvent.click(screen.getByText('Advanced timing'));
    fireEvent.click(screen.getByRole('button', { name: 'Delay' }));
    fireEvent.click(screen.getByRole('button', { name: '+60s' }));
    fireEvent.click(screen.getByRole('button', { name: /test light show/i }));
    expect(onSendCommand).toHaveBeenNthCalledWith(1, expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.TEST_LED, trigger_time: 1700000060,
      uiMeta: expect.objectContaining({ actionKey: 'TEST_LED', triggerSummary: expect.stringMatching(/Executes in 60s/) }),
    }));
    const stop = screen.getByRole('button', { name: /emergency kill/i });
    expect(stop).toHaveTextContent('Airborne aircraft will fall');
    fireEvent.click(stop);
    expect(onSendCommand).toHaveBeenNthCalledWith(2, expect.objectContaining({
      mission_type: DRONE_ACTION_TYPES.KILL_TERMINATE, trigger_time: 0,
    }));
  });

  test('an empty target set cannot send commands or open Move', () => {
    const onSendCommand = jest.fn();
    const onRequestPrecisionMove = jest.fn();
    const { container } = render(<DroneActions actionTypes={DRONE_ACTION_TYPES} targetCount={0} runtimeMode="sitl" onSendCommand={onSendCommand}
      onRequestPrecisionMove={onRequestPrecisionMove} canPrecisionMove />);
    container.querySelectorAll('.drone-actions__group button').forEach((button) => {
      expect(button).toBeDisabled();
      fireEvent.click(button);
    });
    expect(onSendCommand).not.toHaveBeenCalled();
    expect(onRequestPrecisionMove).not.toHaveBeenCalled();
  });
});
