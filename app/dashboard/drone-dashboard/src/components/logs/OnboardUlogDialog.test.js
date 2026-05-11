import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  createDroneUlogDownloadJob,
  eraseAllDroneUlogs,
  getDroneUlogFiles,
  getDroneUlogPolicy,
} from '../../services/logService';

jest.mock('../../services/logService', () => ({
  buildDroneUlogDownloadURL: jest.fn(() => 'http://gcs.test/download/job-1'),
  createDroneUlogDownloadJob: jest.fn(),
  eraseAllDroneUlogs: jest.fn(),
  getDroneUlogDownloadJob: jest.fn(),
  getDroneUlogFiles: jest.fn(),
  getDroneUlogPolicy: jest.fn(),
}));

const OnboardUlogDialog = require('./OnboardUlogDialog').default;

describe('OnboardUlogDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getDroneUlogPolicy.mockResolvedValue({
      policy: {
        download_requires_disarmed: true,
        erase_requires_disarmed: true,
        single_delete_supported: false,
        notes: ['Onboard file-backed PX4 ULogs only.'],
      },
    });
    getDroneUlogFiles.mockResolvedValue({
      files: [
        { id: 7, date_utc: '2026-04-11T10:22:33Z', size_bytes: 1536 },
      ],
    });
  });

  test('loads and renders onboard ULog catalog', async () => {
    render(
      <OnboardUlogDialog
        open
        droneId={5}
        scopeLabel="P12|H5"
        onClose={jest.fn()}
      />,
    );

    expect(await screen.findByText('Onboard ULog')).toBeInTheDocument();
    expect((await screen.findAllByText('P12|H5')).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Log #7/)).toBeInTheDocument();
    expect(await screen.findByText('1.5 KB')).toBeInTheDocument();
    expect(await screen.findByText('Download requires disarmed')).toBeInTheDocument();
  });

  test('starts a staged download from a file row', async () => {
    createDroneUlogDownloadJob.mockResolvedValue({
      job: {
        job_id: 'job-1',
        hw_id: '5',
        pos_id: 12,
        log_id: 7,
        date_utc: '2026-04-11T10:22:33Z',
        size_bytes: 1536,
        status: 'ready',
        progress: 1,
        staged_filename: '5-job.ulg',
        download_filename: 'mds-ulog_P12_H5_20260411T102233Z_L7.ulg',
        created_at: 1,
        updated_at: 1,
        expires_at: 2,
        error: null,
      },
    });

    render(
      <OnboardUlogDialog
        open
        droneId={5}
        scopeLabel="P12|H5"
        onClose={jest.fn()}
      />,
    );

    fireEvent.click(await screen.findByText('Download'));

    await waitFor(() => {
      expect(createDroneUlogDownloadJob).toHaveBeenCalledWith(5, 7);
    });
    expect(await screen.findByText('mds-ulog_P12_H5_20260411T102233Z_L7.ulg')).toBeInTheDocument();
  });

  test('shows erase-all control when onboard logs exist', async () => {
    render(
      <OnboardUlogDialog
        open
        droneId={5}
        scopeLabel="P12|H5"
        onClose={jest.fn()}
      />,
    );

    await screen.findByText('1.5 KB');
    const eraseButton = screen.getByRole('button', { name: /erase all/i });
    expect(eraseButton).toBeEnabled();
    expect(eraseAllDroneUlogs).not.toHaveBeenCalled();
  });

  test('renders structured ULog capability errors as readable text', async () => {
    getDroneUlogFiles.mockRejectedValue({
      response: {
        data: {
          detail: {
            error: 'mavsdk_server_missing',
            message: 'mavsdk_server binary not found',
            ulog_capability: {
              missing_dependency: 'mavsdk_server_missing',
              detail: 'Install mavsdk_server or configure a filesystem fallback.',
            },
          },
        },
      },
    });

    render(
      <OnboardUlogDialog
        open
        droneId={5}
        scopeLabel="P12|H5"
        onClose={jest.fn()}
      />,
    );

    expect(await screen.findByText(/mavsdk_server binary not found/)).toBeInTheDocument();
    expect(await screen.findByText(/Missing dependency: mavsdk_server_missing/)).toBeInTheDocument();
  });
});
