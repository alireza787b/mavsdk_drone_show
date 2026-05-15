import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectoryWorkspaceSummary from './SwarmTrajectoryWorkspaceSummary';

describe('SwarmTrajectoryWorkspaceSummary', () => {
  test('renders workspace summary, session info, and stage actions', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectoryWorkspaceSummary
          workspaceStatus={{
            tone: 'ready',
            title: 'Mission package is ready for launch preflight',
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

    expect(screen.getByText('Mission package is ready for launch preflight')).toBeInTheDocument();
    expect(screen.getByText('session-42')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Swarm Design' })).toHaveAttribute('href', '/swarm-design');
    expect(screen.getByRole('link', { name: 'Advanced Route Editor' })).toHaveAttribute('href', '/trajectory-planning');
    expect(screen.getByText('Swarm trajectory execution policy')).toBeInTheDocument();
    expect(screen.getByText(/This is not live Smart Swarm/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Open Trajectory Planning' })[0]).toHaveAttribute('href', '/trajectory-planning');
    expect(screen.getByText('Generate Cluster Outputs')).toBeInTheDocument();
  });

  test('collapses doctrine and stage review behind one compact summary on mobile surfaces', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectoryWorkspaceSummary
          compact
          workspaceStatus={{
            tone: 'attention',
            title: 'Review package needs attention',
            message: 'One cluster still needs operator review.',
            details: ['Missing follower output: 3'],
          }}
          session={{
            exists: true,
            session_id: 'session-99',
            total_drones: 2,
          }}
          stages={[
            {
              id: 'upload',
              step: 1,
              title: 'Load Leader Paths',
              label: 'Ready',
              tone: 'ready',
              summary: 'All expected leader CSVs are loaded.',
              details: ['Uploaded leaders: 1'],
            },
          ]}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Workspace review & policy')).toBeInTheDocument();
    expect(screen.getByText(/Expand for doctrine and stage status/i)).toBeInTheDocument();
    expect(screen.getByText('Review package needs attention')).toBeInTheDocument();
  });
});
