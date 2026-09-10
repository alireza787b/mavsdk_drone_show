import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import MissionTrigger from './MissionTrigger';
import { DRONE_MISSION_TYPES } from '../constants/droneConstants';

jest.mock('./DashboardSmartSwarmStart', () => () => <button>Start Smart Swarm</button>);

jest.mock('./MissionCard', () => ({ label, onClick }) => (
  <button onClick={onClick}>{label}</button>
));

jest.mock('./MissionDetails', () => (props) => (
  <div>
    <button onClick={props.onSend}>send</button>
    <button onClick={props.onBack}>back</button>
  </div>
));

describe('MissionTrigger', () => {
  test('shows one saved-formation start beside Drone Show instead of the generic schedule picker', () => {
    render(
      <MissionTrigger
        missionTypes={DRONE_MISSION_TYPES}
        onSendCommand={jest.fn()}
      />
    );

    expect(screen.queryByRole('button', { name: 'Smart Swarm' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Start Smart Swarm' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Drone Show' }).parentElement).toBe(
      screen.getByRole('button', { name: 'Start Smart Swarm' }).parentElement,
    );
    expect(
      screen.getByRole('link', { name: 'Smart Swarm Runtime' })
    ).toHaveAttribute('href', '/swarm-design');
  });

  test('forces Custom CSV commands into explicit local mode', () => {
    const onSendCommand = jest.fn();

    render(
      <MissionTrigger
        missionTypes={DRONE_MISSION_TYPES}
        onSendCommand={onSendCommand}
      />
    );

    fireEvent.click(screen.getByText('Custom Show'));
    fireEvent.click(screen.getByText('send'));

    expect(onSendCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        mission_type: DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW,
        auto_global_origin: false,
        use_global_setpoints: false,
      })
    );
  });

  test('includes strict synchronized execution policy for swarm trajectory dispatch', () => {
    const onSendCommand = jest.fn();

    render(
      <MissionTrigger
        missionTypes={DRONE_MISSION_TYPES}
        onSendCommand={onSendCommand}
        referenceNowMs={1_700_000_000_000}
      />
    );

    fireEvent.click(screen.getByText('Swarm Route'));
    fireEvent.click(screen.getByText('send'));

    expect(onSendCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        mission_type: DRONE_MISSION_TYPES.SWARM_TRAJECTORY,
        uiMeta: expect.objectContaining({
          details: expect.arrayContaining([
            expect.objectContaining({
              label: 'Execution policy',
              value: expect.stringMatching(/queue for the shared trigger/i),
            }),
          ]),
        }),
      })
    );
  });
});
