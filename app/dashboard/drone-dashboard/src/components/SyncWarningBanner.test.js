import React from 'react';
import { render, screen } from '@testing-library/react';
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

  test('opens the guided sync plan for out-of-sync drones', async () => {
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

    const link = await screen.findByRole('link', { name: /review sync/i });
    expect(link).toHaveAttribute('href', '/fleet-ops?tab=sync&filter=drift&scope=needs-sync&autoplan=1');
    expect(screen.getByRole('link', { name: /details/i })).toHaveAttribute('href', '/fleet-ops?tab=sync&filter=drift');
  });
});
