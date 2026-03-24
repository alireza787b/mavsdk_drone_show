import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import MissionTrigger from './MissionTrigger';
import { DRONE_MISSION_TYPES } from '../constants/droneConstants';

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
  test('forces Custom CSV commands into explicit local mode', () => {
    const onSendCommand = jest.fn();

    render(
      <MissionTrigger
        missionTypes={DRONE_MISSION_TYPES}
        onSendCommand={onSendCommand}
      />
    );

    fireEvent.click(screen.getByText('CUSTOM CSV DRONE SHOW'));
    fireEvent.click(screen.getByText('send'));

    expect(onSendCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        missionType: String(DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW),
        auto_global_origin: false,
        use_global_setpoints: false,
      })
    );
  });
});
