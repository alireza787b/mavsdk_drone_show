import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectoryWorkspaceSummary from './SwarmTrajectoryWorkspaceSummary';

describe('SwarmTrajectoryWorkspaceSummary', () => {
  test('renders workspace summary, session info, and stage actions', () => {
    render(
      <MemoryRouter>
        <SwarmTrajectoryWorkspaceSummary
          workspaceStatus={{
            tone: 'ready',
            title: 'Mission package is ready for dashboard preflight',
            message: 'Five drone outputs are ready.',
            details: ['Processing session: session-42'],
          }}
          session={{
            exists: true,
            session_id: 'session-42',
            total_drones: 5,
          }}
          stages={[
            {
              id: 'upload',
              step: 1,
              title: 'Load Leader Paths',
              label: 'Ready',
              tone: 'ready',
              summary: 'All expected leader CSVs are loaded.',
              details: ['Uploaded leaders: 1, 5'],
              actionLabel: 'Open Trajectory Planning',
              actionHref: '/trajectory-planning',
            },
            {
              id: 'processing',
              step: 2,
              title: 'Generate Cluster Outputs',
              label: 'Ready',
              tone: 'ready',
              summary: 'Processed outputs are current.',
              details: ['Processed drones: 5'],
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Mission package is ready for dashboard preflight')).toBeInTheDocument();
    expect(screen.getByText('session-42')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Trajectory Planning' })).toHaveAttribute('href', '/trajectory-planning');
    expect(screen.getByText('Generate Cluster Outputs')).toBeInTheDocument();
  });
});
