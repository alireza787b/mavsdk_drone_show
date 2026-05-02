import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Px4ParametersPage from './Px4ParametersPage';
import * as gcsApi from '../services/gcsApiService';
import * as px4ParamsApi from '../services/px4ParamsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';

jest.mock('react-toastify', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warn: jest.fn(),
  },
}));

jest.mock('@mui/x-data-grid', () => ({
  DataGrid: ({ rows, onRowClick }) => (
    <div data-testid="px4-grid">
      {rows.map((row) => (
        <button key={row.id} type="button" onClick={() => onRowClick({ row })}>
          {row.name}
        </button>
      ))}
    </div>
  ),
}));

jest.mock('../services/gcsApiService', () => ({
  buildGcsUrl: jest.fn((value) => `/mock${value}`),
  buildShowPlotUrl: jest.fn((filename) => `/mock/plots/${filename}`),
  GCS_ROUTE_KEYS: {
    customShowImage: '/custom-show/image',
  },
  getFleetConfigResponse: jest.fn(),
  getFleetTelemetryResponse: jest.fn(),
  getSwarmConfigResponse: jest.fn(),
  unwrapFleetTelemetryPayload: jest.fn((payload) => payload),
  unwrapSwarmConfigPayload: jest.fn((payload) => payload),
}));

jest.mock('../services/px4ParamsApiService', () => ({
  diffPx4ParamSnapshot: jest.fn(),
  importQgcParameterFile: jest.fn(),
  getPx4ParamPolicy: jest.fn(),
  getPx4ParamProfile: jest.fn(),
  listPx4ParamProfiles: jest.fn(),
  refreshPx4ParamSnapshots: jest.fn(),
  createPx4ParamPatchJob: jest.fn(),
}));

jest.mock('../utilities/commandLifecycleFeedback', () => ({
  submitCommandWithLifecycleFeedback: jest.fn(),
}));

const snapshotPayload = {
  snapshot: {
    snapshot_id: 'snap-1',
    hw_id: '1',
    component_id: 1,
    px4_docs_version: 'main',
    total_params: 2,
    created_at: Date.now(),
    stale_after_ms: 60000,
  },
  rows: [
    {
      component_id: 1,
      name: 'MAV_SYS_ID',
      value_type: 'int',
      value: 1,
      writable: true,
      docs_url: 'https://docs.px4.io/main/en/advanced_config/parameter_reference.html#MAV_SYS_ID',
      short_description: 'System id',
      long_description: null,
      unit: null,
      group: 'MAVLink',
      category: 'System',
      decimal_places: null,
      increment: 1,
      default_value: 1,
      min_value: 1,
      max_value: 255,
      reboot_required: true,
      metadata_sources: ['vehicle'],
      enum_values: [],
    },
    {
      component_id: 1,
      name: 'MPC_XY_VEL_MAX',
      value_type: 'float',
      value: 12.5,
      writable: true,
      docs_url: 'https://docs.px4.io/main/en/advanced_config/parameter_reference.html#MPC_XY_VEL_MAX',
      short_description: 'Horizontal velocity cap',
      long_description: null,
      unit: 'm/s',
      group: 'Multicopter Position Control',
      category: 'Standard',
      decimal_places: 2,
      increment: 0.5,
      default_value: 10.0,
      min_value: 0,
      max_value: 20,
      reboot_required: false,
      metadata_sources: ['vehicle', 'component_information'],
      enum_values: [],
    },
  ],
};

describe('Px4ParametersPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    const nowSec = Math.floor(Date.now() / 1000);
    window.innerWidth = 1280;
    window.matchMedia = jest.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    }));
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: 1, pos_id: 1, ip: '10.0.0.11' }],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
    });
    gcsApi.getSwarmConfigResponse.mockResolvedValue({ data: [] });
    px4ParamsApi.getPx4ParamPolicy.mockResolvedValue({
      data: {
        docs: { version: 'main' },
        mutations: { require_disarmed: true, supported_component_ids: [1] },
      },
    });
    px4ParamsApi.listPx4ParamProfiles.mockResolvedValue({
      data: {
        profiles: [
          {
            profile_id: 'fleet_geofence_guardrail',
            name: 'Fleet Geofence Guardrail',
            description: 'Starter profile',
            recommended_scope: 'fleet',
            tags: ['starter'],
            entry_count: 2,
            updated_at: Date.now(),
          },
        ],
      },
    });
    px4ParamsApi.getPx4ParamProfile.mockResolvedValue({
      data: {
        profile_id: 'fleet_geofence_guardrail',
        name: 'Fleet Geofence Guardrail',
        description: 'Starter profile',
        recommended_scope: 'fleet',
        tags: ['starter'],
        entries: [
          {
            component_id: 1,
            name: 'GF_ACTION',
            value_type: 'int',
            value: 3,
          },
          {
            component_id: 1,
            name: 'GF_MAX_HOR_DIST',
            value_type: 'float',
            value: 3000,
          },
        ],
        updated_at: Date.now(),
      },
    });
    px4ParamsApi.refreshPx4ParamSnapshots.mockResolvedValue({
      data: {
        snapshots: [snapshotPayload],
        errors: [],
      },
    });
    px4ParamsApi.importQgcParameterFile.mockResolvedValue({
      data: {
        source: 'qgc',
        entries: [
          {
            component_id: 1,
            name: 'MPC_XY_VEL_MAX',
            value_type: 'float',
            value: 13.0,
          },
        ],
        warnings: [],
        skipped_count: 0,
        total_entries: 1,
      },
    });
    px4ParamsApi.diffPx4ParamSnapshot.mockResolvedValue({
      data: {
        differences: [
          {
            component_id: 1,
            name: 'MPC_XY_VEL_MAX',
            value_type: 'float',
            current_value: 12.5,
            desired_value: 13.0,
            changed: true,
          },
        ],
        total_changed: 1,
      },
    });
    px4ParamsApi.createPx4ParamPatchJob.mockResolvedValue({
      data: {
        job_id: 'job-1',
        results: [{ hw_id: '1', applied: true, verified: true, error: null }],
      },
    });
    submitCommandWithLifecycleFeedback.mockResolvedValue({
      commandId: 'cmd-1',
      isTerminal: true,
      outcome: 'completed',
      progress: {
        label: 'Completed',
        message: 'PX4 reboot completed.',
      },
    });
  });

  it('loads the first selected drone and renders refreshed parameter rows', async () => {
    render(<Px4ParametersPage />);

    await waitFor(() => {
      expect(px4ParamsApi.refreshPx4ParamSnapshots).toHaveBeenCalledWith({ hwIds: ['1'], componentId: 1 });
    });

    expect(await screen.findByTestId('px4-grid')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'MAV_SYS_ID' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'MPC_XY_VEL_MAX' })).toBeInTheDocument();
  });

  it('prefers a live drone over stale configured drones for the initial target', async () => {
    const nowSec = Math.floor(Date.now() / 1000);
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec - 3600, heartbeat_last_seen: nowSec - 3600 },
        2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec - 3600, heartbeat_last_seen: nowSec - 3600 },
      2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
    });

    render(<Px4ParametersPage />);

    await waitFor(() => {
      expect(px4ParamsApi.refreshPx4ParamSnapshots).toHaveBeenCalledWith({ hwIds: ['2'], componentId: 1 });
    });
  });

  it('shows concise PX4 metadata guidance with a guide link when metadata is partial', async () => {
    px4ParamsApi.refreshPx4ParamSnapshots.mockResolvedValue({
      data: {
        snapshots: [{
          ...snapshotPayload,
          snapshot: {
            ...snapshotPayload.snapshot,
            metadata_quality: 'raw_values_only',
            metadata_warning: 'PX4 parameter values are available, but metadata labels, groups, defaults, and docs require vehicle component metadata, a matching PX4 parameter catalog, or the optional official PX4 docs reference cache.',
          },
        }],
        errors: [],
      },
    });

    render(<Px4ParametersPage />);

    expect(await screen.findByText('PX4 metadata limited')).toBeInTheDocument();
    expect(screen.getByText('Live values available; reference metadata is partial.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /px4 parameters guide/i })).toHaveAttribute(
      'href',
      expect.stringContaining('docs/px4-parameters.md'),
    );
  });

  it('applies a verified single-parameter patch job from the inspector', async () => {
    render(<Px4ParametersPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'MPC_XY_VEL_MAX' })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('Snapshot ready')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'MPC_XY_VEL_MAX' }));
    expect(await screen.findByRole('dialog', { name: /MPC_XY_VEL_MAX parameter details/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save Parameter' })).not.toBeDisabled();
    fireEvent.change(screen.getByLabelText('Set MPC_XY_VEL_MAX value'), { target: { value: '13.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Parameter' }));

    await waitFor(() => {
      expect(px4ParamsApi.createPx4ParamPatchJob).toHaveBeenCalledWith({
        hwIds: ['1'],
        source: 'manual',
        verifyReadback: true,
        entries: [
          {
            component_id: 1,
            name: 'MPC_XY_VEL_MAX',
            value_type: 'float',
            value: 13.5,
          },
        ],
      });
    });
  });

  it('applies a batch patch to all configured drones from the batch workspace', async () => {
    const nowSec = Math.floor(Date.now() / 1000);
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
        2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
    });

    render(<Px4ParametersPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Batch' }));
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.click(screen.getByRole('button', { name: 'Advanced Manual Entry' }));
    await waitFor(() => {
      expect(screen.getByText('All 2 drones')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Apply Manual Patch' })).not.toBeDisabled();
    });
    fireEvent.change(screen.getByLabelText('Batch parameter name'), { target: { value: 'gf_max_hor_dist' } });
    fireEvent.change(screen.getByLabelText('Batch parameter type'), { target: { value: 'float' } });
    fireEvent.change(screen.getByLabelText('Batch parameter value'), { target: { value: '120' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Manual Patch' }));

    await waitFor(() => {
      expect(px4ParamsApi.createPx4ParamPatchJob).toHaveBeenCalledWith({
        hwIds: ['1', '2'],
        source: 'manual',
        verifyReadback: true,
        entries: [
          {
            component_id: 1,
            name: 'GF_MAX_HOR_DIST',
            value_type: 'float',
            value: 120,
          },
        ],
      });
    });
  });

  it('loads repo-backed profiles and applies a saved profile to a selected batch scope', async () => {
    const nowSec = Math.floor(Date.now() / 1000);
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
        2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      2: { hw_id: '2', pos_id: 2, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
    });

    render(<Px4ParametersPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Profiles' }));
    expect(await screen.findByText('Fleet Geofence Guardrail')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Use in Batch' }));
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply Saved Profile' }));

    await waitFor(() => {
      expect(px4ParamsApi.createPx4ParamPatchJob).toHaveBeenCalledWith({
        hwIds: ['1', '2'],
        source: 'mds_profile',
        verifyReadback: true,
        entries: [
          {
            component_id: 1,
            name: 'GF_ACTION',
            value_type: 'int',
            value: 3,
          },
          {
            component_id: 1,
            name: 'GF_MAX_HOR_DIST',
            value_type: 'float',
            value: 3000,
          },
        ],
      });
    });
  });

  it('shows the qgc import control once the snapshot is ready', async () => {
    render(<Px4ParametersPage />);

    const importButton = await screen.findByRole('button', { name: 'Import QGC File' });
    await waitFor(() => {
      expect(importButton).toBeEnabled();
    });
  });

  it('opens the parameter inspector in a compact dialog on narrow viewports', async () => {
    window.innerWidth = 640;

    render(<Px4ParametersPage />);

    const groupButton = await screen.findByRole('button', { name: /Multicopter Position Control/i });
    fireEvent.click(groupButton);
    fireEvent.click(await screen.findByRole('button', { name: /Open details for MPC_XY_VEL_MAX/i }));

    expect(await screen.findByRole('dialog', { name: /MPC_XY_VEL_MAX parameter details/i })).toBeInTheDocument();
    expect(screen.getByText('Default')).toBeInTheDocument();
    expect(screen.getByText('Range')).toBeInTheDocument();
    expect(screen.getByText('Restart')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'PX4 Docs' })).toBeInTheDocument();
  });

  it('opens the parameter inspector in a dialog on wide desktop layouts too', async () => {
    render(<Px4ParametersPage />);

    const rowButton = await screen.findByRole('button', { name: /MAV_SYS_ID/i });
    fireEvent.click(rowButton);

    expect(await screen.findByRole('dialog', { name: /MAV_SYS_ID parameter details/i })).toBeInTheDocument();
    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getByText('Step')).toBeInTheDocument();
  });

  it('keeps touch desktop-mode view in the compact dialog workflow', async () => {
    window.innerWidth = 1280;
    window.matchMedia = jest.fn().mockImplementation((query) => ({
      matches: query === '(pointer: coarse)',
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    }));

    render(<Px4ParametersPage />);

    const groupButton = await screen.findByRole('button', { name: /Multicopter Position Control/i });
    fireEvent.click(groupButton);
    fireEvent.click(await screen.findByRole('button', { name: /Open details for MPC_XY_VEL_MAX/i }));

    expect(await screen.findByRole('dialog', { name: /MPC_XY_VEL_MAX parameter details/i })).toBeInTheDocument();
  });

  it('shows metadata facts in compact cards when available', async () => {
    window.innerWidth = 640;

    render(<Px4ParametersPage />);

    expect(await screen.findByRole('button', { name: /MAVLink/i })).toBeInTheDocument();
    expect(screen.getByLabelText('Restart required')).toBeInTheDocument();
    expect(screen.getAllByLabelText('PX4 Docs available').length).toBeGreaterThan(0);
  });

  it('allows batch profile apply to online drones only when some targets are offline', async () => {
    const nowSec = Math.floor(Date.now() / 1000);
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false, update_time: nowSec, heartbeat_last_seen: nowSec },
    });

    render(<Px4ParametersPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Batch' }));
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    const skipOffline = await screen.findByLabelText(/Apply to online drones only and skip 1 offline target/i);
    fireEvent.click(skipOffline);
    fireEvent.click(screen.getByRole('button', { name: 'Apply Saved Profile' }));

    await waitFor(() => {
      expect(px4ParamsApi.createPx4ParamPatchJob).toHaveBeenCalledWith({
        hwIds: ['1'],
        source: 'mds_profile',
        verifyReadback: true,
        entries: [
          {
            component_id: 1,
            name: 'GF_ACTION',
            value_type: 'int',
            value: 3,
          },
          {
            component_id: 1,
            name: 'GF_MAX_HOR_DIST',
            value_type: 'float',
            value: 3000,
          },
        ],
      });
    });
  });

  it('dispatches a reboot px4 command from the single-drone workspace', async () => {
    render(<Px4ParametersPage />);

    const rebootButton = await screen.findByRole('button', { name: 'Reboot PX4' });
    await waitFor(() => {
      expect(screen.getByText('Snapshot ready')).toBeInTheDocument();
      expect(rebootButton).not.toBeDisabled();
    });
    fireEvent.click(rebootButton);

    await waitFor(() => {
      expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith({
        missionType: '6',
        target_drones: ['1'],
        triggerTime: '0',
        uiMeta: {
          operatorLabel: 'Reboot PX4',
        },
      }, expect.any(Object));
    });
  });
});
