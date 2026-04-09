import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Px4ParametersPage from './Px4ParametersPage';
import * as gcsApi from '../services/gcsApiService';
import * as px4ParamsApi from '../services/px4ParamsApiService';

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
      decimal_places: null,
      default_value: 1,
      min_value: 1,
      max_value: 255,
      reboot_required: true,
      metadata_sources: ['vehicle'],
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
      decimal_places: 2,
      default_value: 10.0,
      min_value: 0,
      max_value: 20,
      reboot_required: false,
      metadata_sources: ['vehicle', 'component_information'],
    },
  ],
};

describe('Px4ParametersPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: 1, pos_id: 1, ip: '10.0.0.11' }],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false },
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

  it('applies a verified single-parameter patch job from the inspector', async () => {
    render(<Px4ParametersPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'MPC_XY_VEL_MAX' })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('Online')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Save Parameter' })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole('button', { name: 'MPC_XY_VEL_MAX' }));
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
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false },
        2: { hw_id: '2', pos_id: 2, is_armed: false },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false },
      2: { hw_id: '2', pos_id: 2, is_armed: false },
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
    gcsApi.getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    gcsApi.getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: { hw_id: '1', pos_id: 1, is_armed: false },
        2: { hw_id: '2', pos_id: 2, is_armed: false },
      },
      headers: {},
    });
    gcsApi.unwrapFleetTelemetryPayload.mockReturnValue({
      1: { hw_id: '1', pos_id: 1, is_armed: false },
      2: { hw_id: '2', pos_id: 2, is_armed: false },
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
});
