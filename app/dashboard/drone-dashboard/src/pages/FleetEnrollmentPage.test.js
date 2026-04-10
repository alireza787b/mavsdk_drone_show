import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetEnrollmentPage from './FleetEnrollmentPage';
import useFetch from '../hooks/useFetch';
import {
  acceptFleetCandidate,
  ignoreFleetCandidate,
  recoverFleetCandidate,
  rejectFleetCandidate,
  replaceFleetCandidate,
} from '../services/fleetEnrollmentApiService';

jest.mock('../hooks/useFetch');
jest.mock('../services/fleetEnrollmentApiService', () => ({
  acceptFleetCandidate: jest.fn(),
  ignoreFleetCandidate: jest.fn(),
  recoverFleetCandidate: jest.fn(),
  rejectFleetCandidate: jest.fn(),
  replaceFleetCandidate: jest.fn(),
}));

const renderPage = (initialEntry = '/fleet-enrollment') => render(
  <MemoryRouter
    initialEntries={[initialEntry]}
    future={{
      v7_startTransition: true,
      v7_relativeSplatPath: true,
    }}
  >
    <FleetEnrollmentPage />
  </MemoryRouter>
);

describe('FleetEnrollmentPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  function mockFetch({ candidates, config }) {
    useFetch.mockImplementation((endpoint) => {
      if (String(endpoint).startsWith('fleetCandidates')) {
        return {
          data: { candidates },
          loading: false,
          error: null,
        };
      }
      if (endpoint === 'fleetConfig') {
        return {
          data: config,
          loading: false,
          error: null,
        };
      }
      return { data: null, loading: false, error: null };
    });
  }

  test('shows recovery guidance when candidate hw_id already exists in fleet config', () => {
    mockFetch({
      candidates: [
        {
          candidate_id: 'node-12b',
          hw_id: '12',
          hostname: 'drone12b',
          reported_pos_id: '12',
          detected_pos_id: null,
          primary_control_ip: '10.0.0.212',
          ip_addresses: ['10.0.0.212'],
          heartbeat_status: 'online',
          heartbeat_age_sec: 4,
          registration_state: 'conflict',
          conflict_reasons: ['hw_id_already_in_fleet'],
        },
      ],
      config: [
        { hw_id: 12, pos_id: 12, ip: '10.0.0.12', mavlink_port: 14550, serial_port: '', baudrate: 0 },
      ],
    });

    renderPage();

    expect(screen.getByText(/same hardware id already exists in fleet config/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /recover existing node/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /add as new fleet member/i })).toBeDisabled();
  });

  test('shows replacement banner when opened from mission config with a target slot', () => {
    mockFetch({
      candidates: [
        {
          candidate_id: 'hw-101',
          hw_id: '101',
          hostname: 'spare-101',
          reported_pos_id: null,
          detected_pos_id: '12',
          primary_control_ip: '10.0.0.101',
          ip_addresses: ['10.0.0.101'],
          heartbeat_status: 'online',
          heartbeat_age_sec: 6,
          registration_state: 'pending_operator_review',
          conflict_reasons: [],
        },
      ],
      config: [
        { hw_id: 12, pos_id: 12, ip: '10.0.0.12', mavlink_port: 14550, serial_port: '', baudrate: 0 },
      ],
    });

    renderPage('/fleet-enrollment?replace=12');

    expect(screen.getByText(/replacement workflow armed for Drone 12/i)).toBeInTheDocument();
  });

  test('submits accept-as-new through the canonical service', async () => {
    mockFetch({
      candidates: [
        {
          candidate_id: 'hw-101',
          hw_id: '101',
          hostname: 'spare-101',
          reported_pos_id: null,
          detected_pos_id: '15',
          primary_control_ip: '10.0.0.101',
          ip_addresses: ['10.0.0.101'],
          heartbeat_status: 'online',
          heartbeat_age_sec: 6,
          registration_state: 'pending_operator_review',
          conflict_reasons: [],
        },
      ],
      config: [
        { hw_id: 12, pos_id: 12, ip: '10.0.0.12', mavlink_port: 14550, serial_port: '', baudrate: 0 },
      ],
    });

    acceptFleetCandidate.mockResolvedValue({
      data: {
        message: 'Candidate accepted',
        warnings: [],
      },
    });

    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /add as new fleet member/i }));
    fireEvent.click(screen.getByRole('button', { name: /accept as new member/i }));

    await waitFor(() => {
      expect(acceptFleetCandidate).toHaveBeenCalledWith(
        'hw-101',
        expect.objectContaining({
          pos_id: 15,
          ip: '10.0.0.101',
          mavlink_port: 14550,
        }),
        { commit: true },
      );
    });
  });
});
