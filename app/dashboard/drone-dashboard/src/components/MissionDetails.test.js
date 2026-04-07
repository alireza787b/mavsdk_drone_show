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
  targetMode: 'all',
  selectedDrones: [],
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
        package_drone_stats: {
          1: {
            route_entry_time_s: 10,
            mission_clock_s: 70,
            route_motion_time_s: 60,
            max_altitude_msl_m: 1460,
            min_altitude_msl_m: 1450,
            altitude_window_m: 10,
          },
          2: {
            route_entry_time_s: 10,
            mission_clock_s: 68,
            route_motion_time_s: 58,
            max_altitude_msl_m: 1458,
            min_altitude_msl_m: 1452,
            altitude_window_m: 6,
          },
        },
        package_stats: {
          available: true,
          drone_count: 2,
          route_entry_time_s: 10,
          mission_clock_s: 70,
          route_motion_time_s: 60,
          max_altitude_msl_m: 1460,
          min_altitude_msl_m: 1450,
          altitude_window_m: 10,
        },
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

    expect(screen.getByText('Swarm Trajectory Readiness')).toBeInTheDocument();
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
        package_drone_stats: {
          1: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1465,
            min_altitude_msl_m: 1450,
            altitude_window_m: 15,
          },
          2: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1458,
            min_altitude_msl_m: 1451,
            altitude_window_m: 7,
          },
          3: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1462,
            min_altitude_msl_m: 1452,
            altitude_window_m: 10,
          },
        },
        package_stats: {
          available: true,
          drone_count: 3,
          route_entry_time_s: 10,
          mission_clock_s: 72,
          route_motion_time_s: 62,
          max_altitude_msl_m: 1465,
          min_altitude_msl_m: 1450,
          altitude_window_m: 15,
        },
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

    expect(screen.getByText('Swarm Trajectory Readiness')).toBeInTheDocument();
    expect(screen.getByText('Processed package is active. Confirm the final plots before launch.')).toBeInTheDocument();
    expect(screen.getByText('Mission clock:')).toBeInTheDocument();
    expect(screen.getByText('72.0s')).toBeInTheDocument();
    expect(screen.getByText('Altitude envelope:')).toBeInTheDocument();
    expect(screen.getByText('1450.0-1465.0 m MSL • window 15.0 m')).toBeInTheDocument();
    expect(screen.getByText('Strict synchronized launch')).toBeInTheDocument();
    expect(screen.getByText(/queue this mission before the safe pre-trigger window closes/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review & Send Command' })).toBeEnabled();
  });

  test('allows a valid selected subset even when another cluster is incomplete', () => {
    useSwarmClusterStatus.mockReturnValue({
      data: {
        clusters: [
          {
            leader_id: 1,
            follower_ids: [2, 3],
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 3,
            processed_drone_count: 3,
            issues: [],
            advisories: [],
          },
          {
            leader_id: 4,
            follower_ids: [5],
            ready: false,
            leader_uploaded: true,
            state: 'partial_outputs',
            expected_drone_count: 2,
            processed_drone_count: 1,
            issues: ['Follower output missing'],
            advisories: [],
          },
        ],
        follow_map: {
          1: 0,
          2: 1,
          3: 1,
          4: 0,
          5: 4,
        },
        processed_drones: [1, 2, 3, 4],
        package_drone_stats: {
          1: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1465,
            min_altitude_msl_m: 1450,
            altitude_window_m: 15,
          },
          2: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1458,
            min_altitude_msl_m: 1451,
            altitude_window_m: 7,
          },
          3: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1462,
            min_altitude_msl_m: 1452,
            altitude_window_m: 10,
          },
          4: {
            route_entry_time_s: 10,
            mission_clock_s: 65,
            route_motion_time_s: 55,
            max_altitude_msl_m: 1448,
            min_altitude_msl_m: 1445,
            altitude_window_m: 3,
          },
        },
        package_stats: {
          available: true,
          drone_count: 4,
          route_entry_time_s: 10,
          mission_clock_s: 72,
          route_motion_time_s: 62,
          max_altitude_msl_m: 1465,
          min_altitude_msl_m: 1445,
          altitude_window_m: 20,
        },
        session: { exists: true, session_id: 's1', total_drones: 5 },
        cluster_summary: {
          cluster_count: 2,
          ready_cluster_count: 1,
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
        <MissionDetails {...baseProps} targetMode="selected" selectedDrones={['1', '2', '3']} />
      </MemoryRouter>
    );

    expect(screen.getByText('1 out-of-scope cluster remains incomplete, but is outside the current launch scope.')).toBeInTheDocument();
    expect(screen.getAllByText('3 selected drones').length).toBeGreaterThan(0);
    expect(screen.getByText('1450.0-1465.0 m MSL • window 15.0 m')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review & Send Command' })).toBeEnabled();
  });

  test('blocks a selected subset that breaks the leader chain', () => {
    useSwarmClusterStatus.mockReturnValue({
      data: {
        clusters: [
          {
            leader_id: 1,
            follower_ids: [2, 3],
            ready: true,
            leader_uploaded: true,
            state: 'ready',
            expected_drone_count: 3,
            processed_drone_count: 3,
            issues: [],
            advisories: [],
          },
        ],
        follow_map: {
          1: 0,
          2: 1,
          3: 1,
        },
        processed_drones: [1, 2, 3],
        package_drone_stats: {
          1: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1465,
            min_altitude_msl_m: 1450,
            altitude_window_m: 15,
          },
          2: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1458,
            min_altitude_msl_m: 1451,
            altitude_window_m: 7,
          },
          3: {
            route_entry_time_s: 10,
            mission_clock_s: 72,
            route_motion_time_s: 62,
            max_altitude_msl_m: 1462,
            min_altitude_msl_m: 1452,
            altitude_window_m: 10,
          },
        },
        package_stats: {
          available: true,
          drone_count: 3,
          route_entry_time_s: 10,
          mission_clock_s: 72,
          route_motion_time_s: 62,
          max_altitude_msl_m: 1465,
          min_altitude_msl_m: 1450,
          altitude_window_m: 15,
        },
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
        <MissionDetails {...baseProps} targetMode="selected" selectedDrones={['2', '3']} />
      </MemoryRouter>
    );

    expect(screen.getByText('2 leader chains are incomplete: Drone 2 requires leader 1; Drone 3 requires leader 1.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review & Send Command' })).toBeDisabled();
  });
});
