import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MissionPlanSidebar from './MissionPlanSidebar';

const baseProps = {
  drones: [],
  selectedDrones: [],
  onDroneToggle: jest.fn(),
  missionTemplate: 'area_search',
  onMissionTemplateChange: jest.fn(),
  searchCenter: null,
  onSearchCenterChange: jest.fn(),
  searchRadiusM: 250,
  onSearchRadiusChange: jest.fn(),
  onUseMapCenter: jest.fn(),
  searchPath: [],
  onSearchPathChange: jest.fn(),
  corridorWidthM: 80,
  onCorridorWidthChange: jest.fn(),
  onAppendMapCenterToPath: jest.fn(),
  onUndoSearchPathPoint: jest.fn(),
  onClearSearchPath: jest.fn(),
  surveyConfig: {
    survey_altitude_agl: 40,
    cruise_altitude_msl: 50,
    sweep_width_m: 30,
    overlap_percent: 10,
    survey_speed_ms: 5,
    cruise_speed_ms: 10,
    camera_interval_s: 2,
    use_terrain_following: true,
  },
  onConfigChange: jest.fn(),
  onComputePlan: jest.fn(),
  onLaunchMission: jest.fn(),
  coveragePlan: null,
  searchArea: [
    { lat: 37.0, lng: -122.0 },
    { lat: 37.001, lng: -122.0 },
    { lat: 37.001, lng: -122.001 },
  ],
  computing: false,
  launching: false,
  missionProfileId: 'rapid_search',
  onMissionProfileChange: jest.fn(),
  missionLabel: '',
  onMissionLabelChange: jest.fn(),
  missionBrief: '',
  onMissionBriefChange: jest.fn(),
  returnBehavior: 'return_home',
  onReturnBehaviorChange: jest.fn(),
  positionSourceMode: 'live_drone_positions',
  onPositionSourceModeChange: jest.fn(),
  missionCatalog: [],
  currentMissionId: null,
  recoveringMissionId: null,
  loadingMissionCatalog: false,
  onRecoverMission: jest.fn(),
  onStartFreshPlan: jest.fn(),
  targetHwIds: [],
  targetDrones: [],
  targetSummaryLabel: '',
  launchReadiness: { canLaunch: false },
  planNeedsRecompute: false,
  currentMissionState: 'planning',
  originStatus: { state: 'checking', message: 'Checking origin' },
};

const renderSidebar = (overrides = {}) => render(
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <MissionPlanSidebar {...baseProps} {...overrides} />
  </MemoryRouter>
);

describe('MissionPlanSidebar', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('links operators to origin setup when Origin Slots has no configured origin', () => {
    renderSidebar({
      positionSourceMode: 'configured_origin',
      originStatus: { state: 'missing', message: 'Set an origin before using Origin Slots.' },
    });

    const originLink = screen.getByRole('link', { name: 'Set origin' });
    expect(originLink).toHaveAttribute('href', '/mission-config');
    expect(screen.getByText('Set an origin before using Origin Slots.')).toBeInTheDocument();
  });

  it('suggests Origin Slots when selected drones have no fresh Live GPS', () => {
    const onPositionSourceModeChange = jest.fn();
    renderSidebar({
      drones: [
        {
          hw_ID: '1',
          pos_id: 1,
          gpsReady: false,
          quickScoutStatus: { label: 'Offline', className: 'offline', title: 'No telemetry row is available.' },
        },
        {
          hw_ID: '2',
          pos_id: 2,
          gpsReady: true,
          quickScoutStatus: { label: 'Live GPS', className: 'online', title: 'Fresh global GPS position is available.' },
        },
      ],
      selectedDrones: [1],
      onPositionSourceModeChange,
    });

    expect(screen.getByText('No selected slot has fresh Live GPS. Use Origin Slots for draft planning.')).toBeInTheDocument();
    const originSlotButtons = screen.getAllByRole('button', { name: 'Origin Slots' });
    fireEvent.click(originSlotButtons[originSlotButtons.length - 1]);

    expect(onPositionSourceModeChange).toHaveBeenCalledWith('configured_origin');
  });
});
