import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import {
  MissionAltitudeControl,
  MissionDroneSelector,
  MissionGeometrySummary,
  MissionGeometryToolbar,
  MissionJobProgressDialog,
  MissionMapWorkspace,
  MissionPlanStatusBar,
  MissionReviewLaunchDialog,
} from './MissionPlanningComponents';
import { MISSION_GEOMETRY_TYPES } from '../../utilities/missionGeometry';

describe('mission planning shared components', () => {
  test('renders map workspace with toolbar, provider controls, fallback, sidebar, and footer', () => {
    render(
      <MissionMapWorkspace
        title="QuickScout"
        subtitle="Plan and review"
        status={<span>Ready</span>}
        providerControls={<button type="button">Mapbox</button>}
        fallbackNotice={<div>Leaflet fallback active</div>}
        toolbar={<div>Geometry tools</div>}
        sidebar={<div>Planner sidebar</div>}
        footer={<div>Plan status</div>}
      >
        <div>Map canvas</div>
      </MissionMapWorkspace>
    );

    expect(screen.getByRole('region', { name: 'QuickScout' })).toBeInTheDocument();
    expect(screen.getByText('Plan and review')).toBeInTheDocument();
    expect(screen.getByText('Leaflet fallback active')).toBeInTheDocument();
    expect(screen.getByText('Map canvas')).toBeInTheDocument();
    expect(screen.getByText('Planner sidebar')).toBeInTheDocument();
  });

  test('selects geometry tools and exposes edit and clear actions', () => {
    const onSelectTool = jest.fn();
    const onEditGeometry = jest.fn();
    const onClearGeometry = jest.fn();

    render(
      <MissionGeometryToolbar
        activeTool={MISSION_GEOMETRY_TYPES.CORRIDOR}
        disabledTools={[MISSION_GEOMETRY_TYPES.POLYGON]}
        onSelectTool={onSelectTool}
        onEditGeometry={onEditGeometry}
        onClearGeometry={onClearGeometry}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /use point geometry/i }));
    expect(onSelectTool).toHaveBeenCalledWith(MISSION_GEOMETRY_TYPES.POINT);
    expect(screen.getByRole('button', { name: /use area geometry/i })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /edit geometry/i }));
    fireEvent.click(screen.getByRole('button', { name: /clear geometry/i }));
    expect(onEditGeometry).toHaveBeenCalledTimes(1);
    expect(onClearGeometry).toHaveBeenCalledTimes(1);
  });

  test('summarizes valid and blocked mission geometry', () => {
    const { rerender } = render(
      <MissionGeometrySummary
        geometry={{
          type: MISSION_GEOMETRY_TYPES.CORRIDOR,
          points: [
            { lat: 37, lng: -122 },
            { lat: 37.001, lng: -122.001 },
            { lat: 37.002, lng: -122.001 },
          ],
          corridorWidthM: 100,
        }}
      />
    );

    expect(screen.getByText('Valid')).toBeInTheDocument();
    expect(screen.getByText('Width')).toBeInTheDocument();

    rerender(
      <MissionGeometrySummary
        geometry={{
          type: MISSION_GEOMETRY_TYPES.CORRIDOR,
          points: [{ lat: 37, lng: -122 }],
          corridorWidthM: 0,
        }}
      />
    );

    expect(screen.getByText('Blocked')).toBeInTheDocument();
    expect(screen.getByText('Draw at least two corridor vertices.')).toBeInTheDocument();
    expect(screen.getByText('Set a positive corridor width.')).toBeInTheDocument();
  });

  test('toggles drones and shows readiness states', () => {
    const onToggleDrone = jest.fn();
    render(
      <MissionDroneSelector
        drones={[
          { id: 1, label: 'Rescue 1' },
          { id: 2, label: 'Rescue 2' },
        ]}
        selectedIds={[1]}
        readinessById={{
          1: { status: 'ready', label: 'Ready', detail: 'GPS valid' },
          2: { status: 'blocked', label: 'Blocked', detail: 'No global position', blocked: true },
        }}
        onToggleDrone={onToggleDrone}
      />
    );

    expect(screen.getByText('1 selected')).toBeInTheDocument();
    expect(screen.getByText('GPS valid')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/rescue 1/i));
    expect(onToggleDrone).toHaveBeenCalledWith('1');
    expect(screen.getByLabelText(/rescue 2/i)).toBeDisabled();
  });

  test('changes altitude mode and value with explicit terrain status', () => {
    const onModeChange = jest.fn();
    const onValueChange = jest.fn();

    render(
      <MissionAltitudeControl
        mode="agl"
        valueM={80}
        onModeChange={onModeChange}
        onValueChange={onValueChange}
        terrainStatus={{ status: 'warning', label: 'Estimated terrain', detail: 'Provider unavailable' }}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /msl fixed altitude/i }));
    expect(onModeChange).toHaveBeenCalledWith('fixed_msl');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '90' } });
    expect(onValueChange).toHaveBeenCalledWith('90');
    expect(screen.getByText('Estimated terrain')).toBeInTheDocument();
    expect(screen.getByText('Provider unavailable')).toBeInTheDocument();
  });

  test('renders progress dialog with cancel and failed retry actions', () => {
    const onCancel = jest.fn();
    const onRetry = jest.fn();
    const onClose = jest.fn();
    const { rerender } = render(
      <MissionJobProgressDialog
        open
        job={{ status: 'running', phase: 'Terrain lookup', progressPercent: 35, message: 'Checking route' }}
        onCancel={onCancel}
        onRetry={onRetry}
        onClose={onClose}
      />
    );

    expect(screen.getByRole('dialog', { name: /planning mission/i })).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '35');
    expect(screen.queryByRole('button', { name: /close dialog/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^close$/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(
      <MissionJobProgressDialog
        open
        job={{ status: 'failed', error: 'No live GPS position', progressPercent: 100 }}
        onCancel={onCancel}
        onRetry={onRetry}
        onClose={onClose}
      />
    );

    expect(screen.getByText('No live GPS position')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /close dialog/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test('blocks launch review confirmation until blockers are resolved', () => {
    const onConfirm = jest.fn();
    const onCancel = jest.fn();
    const { rerender } = render(
      <MissionReviewLaunchDialog
        open
        mission={{ Mode: 'QuickScout', Aircraft: '2 selected', Altitude: 'AGL terrain' }}
        blockers={['Drone 2 has no global position.']}
        warnings={['Terrain provider is degraded.']}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    expect(screen.getByRole('dialog', { name: /review mission/i })).toBeInTheDocument();
    expect(screen.getByText('Drone 2 has no global position.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /launch/i })).toBeDisabled();

    rerender(
      <MissionReviewLaunchDialog
        open
        mission={{ Mode: 'QuickScout', Aircraft: '2 selected', Altitude: 'AGL terrain' }}
        blockers={[]}
        warnings={['Terrain provider is degraded.']}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /launch/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test('renders compact status bar and action', () => {
    const onAction = jest.fn();
    render(
      <MissionPlanStatusBar
        mode="QuickScout"
        dronesLabel="2 aircraft"
        geometryStatus={{ valid: true, label: 'Corridor valid' }}
        altitudeLabel="AGL terrain"
        readiness={{ status: 'ready', label: 'Ready' }}
        actionLabel="Review"
        onAction={onAction}
      />
    );

    const status = screen.getByRole('status', { name: /mission plan status/i });
    expect(within(status).getByText('Corridor valid')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /review/i }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
