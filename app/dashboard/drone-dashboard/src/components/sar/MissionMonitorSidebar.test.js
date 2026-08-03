import React from 'react';
import { render, screen } from '@testing-library/react';

import MissionMonitorSidebar from './MissionMonitorSidebar';

jest.mock('./DroneStatusCard', () => ({ droneState }) => (
  <div data-testid="drone-status-card">{droneState.hw_id}</div>
));

jest.mock('./MissionRecoveryPanel', () => () => <div data-testid="mission-recovery-panel" />);

describe('MissionMonitorSidebar', () => {
  it('shows mission package context for corridor-search missions', () => {
    render(
      <MissionMonitorSidebar
        missionStatus={{
          operation_phase: 'holding',
          status_summary: 'Assigned drones are holding on operator command.',
          recommended_operator_action: 'Generate a follow-up package from current state.',
          latest_command_batch: {
            action: 'pause',
            state: 'completed',
            receipt: {
              command_id: 'command-pause-1',
              tracking_url: '/api/v1/commands/command-pause-1',
              message: 'Tracked pause command queued.',
            },
            targets: {
              '1': { hw_id: '1', state: 'completed' },
            },
          },
          drone_states: {
            '1': { hw_id: '1', state: 'paused', status_note: 'Holding on operator command' },
          },
        }}
        statusError="GCS unavailable"
        findings={[]}
        missionCatalog={[]}
        currentMissionId="mission-corridor"
        recoveringMissionId={null}
        loadingMissionCatalog={false}
        onRecoverMission={() => {}}
        missionLabel="Harbor corridor"
        missionTemplate="corridor_search"
        missionBrief="Sweep the channel approach"
        totalAreaSqM={42000}
        estimatedCoverageTimeS={540}
        searchArea={[]}
        searchCenter={null}
        searchRadiusM={null}
        searchPath={[
          { lat: 37.0, lng: -122.0 },
          { lat: 37.001, lng: -122.001 },
          { lat: 37.002, lng: -122.002 },
        ]}
        corridorWidthM={110}
        selectedFinding={null}
        onFindingSelect={() => {}}
        savingFinding={false}
        deletingFinding={false}
        onSaveFinding={() => {}}
        onDeleteFinding={() => {}}
        missionHandoff={{
          mission_id: 'mission-corridor',
          finding_count: 0,
          reviewed_finding_count: 0,
          unresolved_finding_count: 0,
          evidence_ref_count: 0,
          brief_text: 'Harbor corridor is paused in holding phase.',
          findings: [],
        }}
        loadingMissionHandoff={false}
        onCopyMissionHandoff={() => {}}
        onExportMissionHandoff={() => {}}
      />
    );

    expect(screen.getByText('Mission Package')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Mission status refresh failed: GCS unavailable. Last displayed state may be stale.'
    );
    expect(screen.getByText('Corridor Search')).toBeInTheDocument();
    expect(screen.getByText('Holding')).toBeInTheDocument();
    expect(screen.getByText('Route-centered corridor package')).toBeInTheDocument();
    expect(screen.getByText('Route 3 points')).toBeInTheDocument();
    expect(screen.getByText('Width 110 m')).toBeInTheDocument();
    expect(screen.getByText('Sweep the channel approach')).toBeInTheDocument();
    expect(screen.getByText('Assigned drones are holding on operator command.')).toBeInTheDocument();
    expect(screen.getByText('Latest Tracked Command')).toBeInTheDocument();
    expect(screen.getByText('Execution completed successfully for 1 target.')).toBeInTheDocument();
    expect(screen.getByText('1 completed')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open command tracker' })).toHaveAttribute(
      'href',
      '/api/v1/commands/command-pause-1'
    );
    expect(screen.getByText('Handoff')).toBeInTheDocument();
    expect(screen.getByText('Harbor corridor is paused in holding phase.')).toBeInTheDocument();
    expect(screen.getByText('Mark findings from the map to capture observations, triage them, and keep the mission handoff clean.')).toBeInTheDocument();
    expect(screen.getByTestId('drone-status-card')).toHaveTextContent('1');
  });
});
