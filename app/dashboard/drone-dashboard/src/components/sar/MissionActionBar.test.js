import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import MissionActionBar from './MissionActionBar';

describe('MissionActionBar', () => {
  it('fails closed when backend control authority is unavailable', () => {
    render(
      <MissionActionBar
        missionState="executing"
        onReplan={jest.fn()}
        onPause={jest.fn()}
        onAbort={jest.fn()}
      />
    );

    screen.getAllByRole('button').forEach((button) => {
      expect(button).toBeDisabled();
    });
  });

  it('offers a follow-up replan when the mission is holding', () => {
    const onReplan = jest.fn();
    const onPause = jest.fn();
    const onAbort = jest.fn();

    render(
      <MissionActionBar
        missionState="paused"
        controlAvailability={{
          pause_enabled: false,
          pause_reason: 'Aircraft are already holding on operator command.',
          replan_enabled: true,
          replan_reason: 'Plan a follow-up package from current aircraft state.',
          abort_enabled: true,
        }}
        onReplan={onReplan}
        onPause={onPause}
        onAbort={onAbort}
      />
    );

    const buttons = screen.getAllByRole('button');
    fireEvent.click(buttons[0]);
    expect(onReplan).toHaveBeenCalledTimes(1);
    expect(buttons[1]).toBeDisabled();
  });

  it('confirms mission abort in a centered dialog', () => {
    const onAbort = jest.fn();

    render(
      <MissionActionBar
        missionState="executing"
        controlAvailability={{
          pause_enabled: true,
          replan_enabled: false,
          abort_enabled: true,
        }}
        returnBehavior="hold_position"
        onReplan={jest.fn()}
        onPause={jest.fn()}
        onAbort={onAbort}
      />
    );

    const buttons = screen.getAllByRole('button');
    fireEvent.click(buttons[2]);

    expect(screen.getByRole('dialog', { name: 'End QuickScout Mission' })).toBeInTheDocument();
    expect(screen.getByText(/hold position/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'End Mission' }));

    expect(onAbort).toHaveBeenCalledTimes(1);
  });
});
