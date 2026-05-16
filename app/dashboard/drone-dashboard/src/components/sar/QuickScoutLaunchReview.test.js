import React from 'react';
import { render, screen } from '@testing-library/react';

import QuickScoutLaunchReview from './QuickScoutLaunchReview';

jest.mock('../CommandPreflightSummary', () => () => <div data-testid="command-preflight-summary" />);

describe('QuickScoutLaunchReview', () => {
  const baseProps = {
    coveragePlan: {
      total_area_sq_m: 42000,
      estimated_coverage_time_s: 540,
    },
    missionLabel: 'Harbor corridor',
    missionProfileId: 'rapid_search',
    surveyConfig: {
      algorithm: 'boustrophedon',
      survey_altitude_agl: 40,
      sweep_width_m: 30,
      survey_speed_ms: 5,
      use_terrain_following: true,
    },
    targetHwIds: ['1', '2'],
    targetSummaryLabel: '2 assigned drones',
    targetDrones: [],
    launchReadiness: {
      canLaunch: true,
      blockers: [],
      warnings: [],
    },
  };

  it('renders corridor-specific launch review context', () => {
    render(
      <QuickScoutLaunchReview
        {...baseProps}
        missionTemplate="corridor_search"
        searchPath={[
          { lat: 37.0, lng: -122.0 },
          { lat: 37.001, lng: -122.001 },
          { lat: 37.002, lng: -122.002 },
        ]}
        corridorWidthM={110}
      />
    );

    expect(screen.getByText('Corridor Search')).toBeInTheDocument();
    expect(screen.getByText('Route-centered corridor package')).toBeInTheDocument();
    expect(screen.getByText('Route 3 points')).toBeInTheDocument();
    expect(screen.getByText('Width 110 m')).toBeInTheDocument();
    expect(screen.getByTestId('command-preflight-summary')).toBeInTheDocument();
  });

  it('renders point-search launch review context', () => {
    render(
      <QuickScoutLaunchReview
        {...baseProps}
        missionTemplate="last_known_point"
        searchCenter={{ lat: 37.25, lng: -122.15 }}
        searchRadiusM={180}
      />
    );

    expect(screen.getByText('Last Known Point')).toBeInTheDocument();
    expect(screen.getByText('Point-centered search envelope')).toBeInTheDocument();
    expect(screen.getByText('Center 37.2500, -122.1500')).toBeInTheDocument();
    expect(screen.getByText('Radius 180 m')).toBeInTheDocument();
  });

  it('marks configured-origin packages as staged until live revalidation', () => {
    render(
      <QuickScoutLaunchReview
        {...baseProps}
        coveragePlan={{
          ...baseProps.coveragePlan,
          position_source_mode: 'configured_origin',
          requires_revalidation: true,
        }}
      />
    );

    expect(screen.getByText('Staged plan needs live revalidation')).toBeInTheDocument();
    expect(screen.getByText('Configured origin')).toBeInTheDocument();
    expect(screen.getByText('Origin slots:')).toBeInTheDocument();
  });
});
