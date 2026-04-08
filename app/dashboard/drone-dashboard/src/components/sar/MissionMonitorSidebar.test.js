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
          drone_states: {
            '1': { hw_id: '1', state: 'executing' },
          },
        }}
        pois={[]}
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
      />
    );

    expect(screen.getByText('Mission Package')).toBeInTheDocument();
    expect(screen.getByText('Corridor Search')).toBeInTheDocument();
    expect(screen.getByText('Route-centered corridor package')).toBeInTheDocument();
    expect(screen.getByText('Route 3 points')).toBeInTheDocument();
    expect(screen.getByText('Width 110 m')).toBeInTheDocument();
    expect(screen.getByText('Sweep the channel approach')).toBeInTheDocument();
    expect(screen.getByTestId('drone-status-card')).toHaveTextContent('1');
  });
});
