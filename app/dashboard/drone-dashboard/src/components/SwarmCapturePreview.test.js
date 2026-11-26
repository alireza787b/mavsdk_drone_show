import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SwarmCapturePreview from './SwarmCapturePreview';
import { deriveSwarmCaptureDraft } from '../utilities/swarmCaptureDraft';

jest.mock('../hooks/useSwarmCaptureLiveView', () => () => ({ positions: [], freshCount: 0 }));

const assignments = [{ hw_id: '1', follow: '0' }, { hw_id: '2', follow: '1' }, { hw_id: '3', follow: '2' }];
const request = { hwIds: ['1', '2', '3'], clusterId: '1' };
const snapshot = { current_heights_available: true, observations: {
  1: { north_m: 0, east_m: 0, planned_up_m: 0, current_up_m: 0 },
  2: { north_m: 2, east_m: 0, planned_up_m: 0.3, current_up_m: -0.3 },
  3: { north_m: 4, east_m: 0, planned_up_m: 0.7, current_up_m: -1.2 },
} };

function preview(heightMode) {
  const settings = { leaderId: '1', frame: 'ned', heightMode };
  return <SwarmCapturePreview request={request} snapshot={snapshot} settings={settings}
    candidate={deriveSwarmCaptureDraft(assignments, snapshot, settings)} labels={{}} />;
}

test('height from leader matches plotted draft across all modes, including a relay', () => {
  const { rerender } = render(preview('keep'));
  fireEvent.click(screen.getByRole('button', { name: 'Side' }));
  fireEvent.click(screen.getByRole('button', { name: 'H3, follower' }));
  expect(screen.getByText('Height from leader 0.7 m')).toBeInTheDocument();

  rerender(preview('level'));
  expect(screen.getByText('Height from leader 0 m')).toBeInTheDocument();
  expect(screen.getByText('Up · metres · same height')).toBeInTheDocument();
  const plottedY = name => screen.getByRole('button', { name }).getAttribute('transform').split(' ')[1];
  expect(plottedY('H3, follower')).toBe(plottedY('H1, leader'));

  rerender(preview('current'));
  expect(screen.getByText('Height from leader -1.2 m')).toBeInTheDocument();
  expect(plottedY('H3, follower')).not.toBe(plottedY('H1, leader'));
});
