import React from 'react';
import { render, screen } from '@testing-library/react';

import DroneReadinessReport from './DroneReadinessReport';
import { FIELD_NAMES } from '../constants/fieldMappings';

describe('DroneReadinessReport', () => {
  test('hides compact readiness block when the drone is cleanly ready', () => {
    const { container } = render(
      <DroneReadinessReport
        drone={{
          [FIELD_NAMES.IS_READY_TO_ARM]: true,
          [FIELD_NAMES.READINESS_STATUS]: 'ready',
          [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
          [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
          [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
          [FIELD_NAMES.STATUS_MESSAGES]: [],
          [FIELD_NAMES.READINESS_CHECKS]: [],
        }}
        runtimeStatus={{ level: 'online' }}
        variant="compact"
      />
    );

    expect(container.firstChild).toBeNull();
  });

  test('keeps compact readiness block visible when warnings exist', () => {
    render(
      <DroneReadinessReport
        drone={{
          [FIELD_NAMES.IS_READY_TO_ARM]: false,
          [FIELD_NAMES.READINESS_STATUS]: 'warning',
          [FIELD_NAMES.READINESS_SUMMARY]: 'GPS quality needs review.',
          [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
          [FIELD_NAMES.PREFLIGHT_WARNINGS]: [
            {
              source: 'telemetry',
              severity: 'warning',
              message: 'GPS quality needs review.',
            },
          ],
          [FIELD_NAMES.STATUS_MESSAGES]: [],
          [FIELD_NAMES.READINESS_CHECKS]: [],
        }}
        runtimeStatus={{ level: 'online' }}
        variant="compact"
      />
    );

    expect(screen.getByText('Review Warnings')).toBeInTheDocument();
    expect(screen.getAllByText('GPS quality needs review.')).toHaveLength(2);
  });

  test('hides compact readiness block when only readiness checks are present', () => {
    const { container } = render(
      <DroneReadinessReport
        drone={{
          [FIELD_NAMES.IS_READY_TO_ARM]: true,
          [FIELD_NAMES.READINESS_STATUS]: 'ready',
          [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
          [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
          [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
          [FIELD_NAMES.STATUS_MESSAGES]: [],
          [FIELD_NAMES.READINESS_CHECKS]: [
            {
              id: 'gps',
              label: 'GPS lock',
              ready: true,
              detail: '3D fix available.',
            },
          ],
        }}
        runtimeStatus={{ level: 'online' }}
        variant="compact"
      />
    );

    expect(container.firstChild).toBeNull();
  });

  test('keeps only the advisory summary visible when the drone is ready with link warnings', () => {
    const nowMs = Date.now();

    render(
      <DroneReadinessReport
        drone={{
          [FIELD_NAMES.IS_READY_TO_ARM]: true,
          [FIELD_NAMES.READINESS_STATUS]: 'ready',
          [FIELD_NAMES.READINESS_SUMMARY]: 'Ready to fly',
          [FIELD_NAMES.PREFLIGHT_BLOCKERS]: [],
          [FIELD_NAMES.PREFLIGHT_WARNINGS]: [],
          [FIELD_NAMES.STATUS_MESSAGES]: [],
          [FIELD_NAMES.READINESS_CHECKS]: [],
          [FIELD_NAMES.PREFLIGHT_LAST_UPDATE]: nowMs,
        }}
        runtimeStatus={{ level: 'degraded' }}
        variant="compact"
      />
    );

    expect(screen.queryByText('Ready to Fly')).not.toBeInTheDocument();
    expect(screen.getByText('1 advisory')).toBeInTheDocument();
  });
});
