import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SyncWarningBanner from './SyncWarningBanner';
import { getUnifiedGitStatusResponse } from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({
  getUnifiedGitStatusResponse: jest.fn(),
}));

describe('SyncWarningBanner', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });
  afterEach(() => jest.useRealTimers());

  test('opens a read-only software review, not automatic sync preparation', async () => {
    getUnifiedGitStatusResponse.mockResolvedValue({
      data: {
        needs_sync_count: 2,
        total_drones: 2,
      },
    });

    render(
      <MemoryRouter>
        <SyncWarningBanner />
      </MemoryRouter>,
    );

    const link = await screen.findByRole('link', { name: /review aircraft software/i });
    expect(link).toHaveAttribute('href', '/fleet-ops?tab=sync&filter=drift');
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByText('Software differs')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('unconfirmed revision is not reported as a proven software difference', async () => {
    getUnifiedGitStatusResponse.mockResolvedValue({ data: { needs_sync_count: 0, unknown_count: 2 } });
    render(<MemoryRouter><SyncWarningBanner /></MemoryRouter>);
    expect(await screen.findByText('Version unavailable')).toBeInTheDocument();
    expect(screen.queryByText('Software differs')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveClass('is-unconfirmed');
  });

  test('brief refresh failure retains the same notice; aged evidence becomes unconfirmed', async () => {
    jest.useFakeTimers();
    getUnifiedGitStatusResponse.mockResolvedValueOnce({ data: { needs_sync_count: 1 } }).mockRejectedValue(new Error('network'));
    render(<MemoryRouter><SyncWarningBanner /></MemoryRouter>);
    await act(async () => {});
    const notice = screen.getByRole('status');
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(screen.getByRole('status')).toBe(notice);
    expect(screen.getByText('Software differs')).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(20000); });
    expect(screen.getByRole('status')).toBe(notice);
    expect(screen.getByText('Software status unavailable')).toBeInTheDocument();
  });

  test('dismissal survives identical refreshes but not a changed aircraft at the same count', async () => {
    jest.useFakeTimers();
    const data = { needs_sync_count: 1, git_status: { '1': { commit: 'old-a', in_sync_with_gcs: false } } };
    getUnifiedGitStatusResponse.mockResolvedValue({ data });
    render(<MemoryRouter><SyncWarningBanner /></MemoryRouter>);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss software notice' }));
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    getUnifiedGitStatusResponse.mockResolvedValue({ data: { ...data, git_status: { '2': { commit: 'old-b', in_sync_with_gcs: false } } } });
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  test('a hanging request never overlaps and is aborted on unmount', async () => {
    jest.useFakeTimers();
    getUnifiedGitStatusResponse.mockImplementation(() => new Promise(() => {}));
    const view = render(<MemoryRouter><SyncWarningBanner /></MemoryRouter>);
    await act(async () => { jest.advanceTimersByTime(40000); });
    expect(getUnifiedGitStatusResponse).toHaveBeenCalledTimes(1);
    const { signal } = getUnifiedGitStatusResponse.mock.calls[0][0];
    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
