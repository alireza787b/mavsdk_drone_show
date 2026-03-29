import { buildTrajectoryAttentionItems, validateWaypointSequence } from './SpeedCalculator';

const countLabel = (count = 0, singular, plural = `${singular}s`) => `${count} ${count === 1 ? singular : plural}`;

export const buildTrajectoryMissionReadiness = ({ waypoints = [], stats = {} }) => {
  const blockers = [];
  const advisories = [];
  const notes = [];

  if (waypoints.length === 1) {
    blockers.push({
      tone: 'danger',
      code: 'single_waypoint',
      text: 'Add at least one more waypoint to define a usable route before mission launch.',
    });
  }

  const validation = validateWaypointSequence(waypoints);
  const timeConflictCount = validation.issues.filter((issue) => issue.issue === 'time_conflict').length;

  if (timeConflictCount > 0) {
    blockers.push({
      tone: 'danger',
      code: 'time_conflict',
      text: `${countLabel(timeConflictCount, 'timing conflict')} break${timeConflictCount === 1 ? 's' : ''} mission chronology.`,
    });
  }

  buildTrajectoryAttentionItems(stats).forEach((item) => {
    if (item.tone === 'danger') {
      blockers.push({ ...item, code: 'speed_envelope' });
      return;
    }

    if (item.tone === 'warning') {
      advisories.push({ ...item, code: 'operator_review' });
      return;
    }

    notes.push({ ...item, code: 'mission_note' });
  });

  if (waypoints.length === 0) {
    return {
      blockers,
      advisories,
      notes,
      posture: {
        tone: 'neutral',
        label: 'Not ready',
        summary: 'Add waypoints before assigning this path to a swarm leader.',
        transferLabel: 'Send to Leader',
      },
    };
  }

  if (blockers.length > 0) {
    return {
      blockers,
      advisories,
      notes,
      posture: {
        tone: 'danger',
        label: 'Draft only',
        summary: 'This path can be uploaded for draft review, but launch blockers still need correction before processing or execution.',
        transferLabel: 'Send Draft to Leader',
      },
    };
  }

  if (advisories.length > 0) {
    return {
      blockers,
      advisories,
      notes,
      posture: {
        tone: 'warning',
        label: 'Review required',
        summary: 'This path is internally usable, but operator review is still required before processing and mission launch.',
        transferLabel: 'Send for Review',
      },
    };
  }

  return {
    blockers,
    advisories,
    notes,
    posture: {
      tone: 'success',
      label: 'Ready to process',
      summary: 'This path is internally consistent and ready to assign to a leader cluster for swarm processing.',
      transferLabel: 'Send to Leader',
    },
  };
};
