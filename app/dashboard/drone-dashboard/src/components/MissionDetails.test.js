import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import MissionDetails from './MissionDetails';
import { DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { COMMAND_SCHEDULE_MODES } from '../utilities/commandScheduling';
import useFetch from '../hooks/useFetch';
import useSwarmClusterStatus from '../hooks/useSwarmClusterStatus';

jest.mock('../hooks/useFetch');
jest.mock('../hooks/useSwarmClusterStatus');
jest.mock('./MissionReadinessCard', () => () => <div data-testid="mission-readiness-card" />);

const baseProps = {
  missionType: DRONE_MISSION_TYPES.SWARM_TRAJECTORY,
  icon: '✈️',
  label: 'Swarm Trajectory',
  description: 'Test mission',
  scheduleMode: COMMAND_SCHEDULE_MODES.NOW,
  timeDelay: 10,
  selectedDateTime: '',
  onTimeDelayChange: jest.fn(),
  onTimePickerChange: jest.fn(),
  onScheduleModeChange: jest.fn(),
  autoGlobalOrigin: false,
  onAutoGlobalOriginChange: jest.fn(),
  useGlobalSetpoints: true,
  onUseGlobalSetpointsChange: jest.fn(),
  delayPresets: [5, 10, 30],
  referenceNowMs: Date.now(),
  clockOffsetLabel: 'server +0s',
  onSend: jest.fn(),
  onBack: jest.fn(),
};

describe('MissionDetails Swarm Trajectory gating', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useFetch.mockReturnValue({ data: null, error: null, loading: false });
  });

  test('disables mission send when cluster readiness reports partial outputs', () => {
    useSwarmClusterStatus.mockReturnValue({
      data: {
        clusters: [
          {
            leader_id: 1,
            ready: false,
            leader_uploaded: true,
            state: 'partial_outputs',
            expected_drone_count: 3,
            processed_drone_count: 2,
            issues: ['Follower output missing'],
            advisories: [],
          },
        ],
        processed_drones: [1, 2],
        session: { exists: true, session_id: 's1', total_drones: 3 },
        cluster_summary: {
          cluster_count: 1,
          ready_cluster_count: 0,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 1,
          missing_upload_cluster_count: 0,
          overall_state: 'partial',
        },
      },
      error: null,
      loading: false,
      refresh: jest.fn(),
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MissionDetails {...baseProps} />
      </MemoryRouter>
    );

    expect(screen.getByText('Swarm Trajectory Launch Snapshot')).toBeInTheDocument();
    expect(screen.getByText('1 cluster still has partial outputs.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review & Send Command' })).toBeDisabled();
  });

  test('enables mission send when processed package is fully ready', () => {
    useSwarmClusterStatus.mockReturnValue({
      data: {
        clusters: [
          {
            leader_id: 1,
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 3,
            processed_drone_count: 3,
            issues: [],
            advisories: [],
          },
        ],
        processed_drones: [1, 2, 3],
        session: { exists: true, session_id: 's1', total_drones: 3 },
        cluster_summary: {
          cluster_count: 1,
          ready_cluster_count: 1,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 0,
          missing_upload_cluster_count: 0,
          overall_state: 'ready',
        },
      },
      error: null,
      loading: false,
      refresh: jest.fn(),
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MissionDetails {...baseProps} />
      </MemoryRouter>
    );

    expect(screen.getByText('Swarm Trajectory Launch Snapshot')).toBeInTheDocument();
    expect(screen.getByText('Processed swarm package is active. Confirm the final plots match the intended leader paths before launch.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review & Send Command' })).toBeEnabled();
  });
});
