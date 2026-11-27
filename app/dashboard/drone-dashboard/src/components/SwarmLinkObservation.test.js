import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { LeaderLinkDetails, readLeaderLink } from './SwarmLinkObservation';
import SwarmClusterDiagram from './SwarmClusterDiagram';

const leader = { hw_id: '1', follow: '0' };
const follower = { hw_id: '2', follow: '1', available: true, link_observation: {
  state: 'delayed', session_id: 'run', hw_id: '2', leader_hw_id: '1', valid_until_ms: 11000,
  position_age_ms: 912, heading_age_ms: 910, max_gap_ms: null, transport: 'http-fallback',
} };
test.each([
  [{}, 'other run', 6000],
  [{ follow: '3' }, 'run', 6000],
  [{ hw_id: '4' }, 'run', 6000],
  [{ available: false }, 'run', 6000],
  [{ link_observation: null }, 'run', 6000],
  [{}, 'run', 11000],
])('unknown links cannot reuse another edge, session or expired measurement', (override, run, now) => {
  expect(readLeaderLink({ ...follower, ...override }, run, now)).toEqual({ state: 'unknown' });
});

test('the existing aircraft inspector carries the link and accepts an explicit row selection', () => {
  const select = jest.fn();
  const observation = readLeaderLink(follower, 'run', 10999);
  render(<><SwarmClusterDiagram members={[leader, follower]} links={{ '2': observation }} onSelect={select} />
    <LeaderLinkDetails observation={observation} follow="1" /></>);
  const row = screen.getByRole('button', { name: /Drone 2/i });
  expect(row).toHaveAccessibleDescription('Leader H1 · Updates delayed');
  fireEvent.click(row);
  expect(select).toHaveBeenCalledWith('2');
  expect(screen.getByText('912 ms')).toBeVisible();
  expect(screen.getByText('Longest update gap').nextSibling).toHaveTextContent('Unknown');
  expect(screen.getByText('HTTP fallback')).toBeVisible();
  expect(readLeaderLink(leader, 'run', 1)).toBeNull();
});
