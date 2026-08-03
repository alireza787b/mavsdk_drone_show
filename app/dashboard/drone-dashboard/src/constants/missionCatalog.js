import missionIdentities from '../generated/missionIdentities.generated.json';

/**
 * Canonical dashboard metadata for MDS command identities.
 *
 * Numeric values are generated from src/enums.py. Keep operator labels, telemetry labels,
 * descriptions, and status styling here so dashboard surfaces cannot drift.
 * NONE intentionally has different command/status labels: it is an explicit
 * cancel command in controls and the absence of an active mission in status.
 */

const metadataEntries = [
  {
    key: 'NONE',
    kind: 'mission',
    commandLabel: 'Cancel Mission',
    statusLabel: 'No Mission',
    shortLabel: 'Cancel Mission',
    statusClass: 'mission-none',
    description: 'Cancel the active mission for the current target scope immediately.',
    missionPickerOrder: 99,
  },
  {
    key: 'DRONE_SHOW_FROM_CSV',
    kind: 'mission',
    commandLabel: 'Drone Show from CSV',
    statusLabel: 'Drone Show from CSV',
    shortLabel: 'Drone Show from CSV',
    statusClass: 'mission-performance',
    description: 'Launch the active SkyBrush package with synchronized timing and optional launch correction.',
    missionPickerOrder: 10,
  },
  {
    key: 'SMART_SWARM',
    kind: 'mission',
    commandLabel: 'Smart Swarm',
    statusLabel: 'Smart Swarm',
    shortLabel: 'Smart Swarm',
    statusClass: 'mission-performance',
    description: 'Start the published leader-follower topology for live formation flight.',
    missionPickerOrder: 30,
  },
  {
    key: 'CUSTOM_CSV_DRONE_SHOW',
    kind: 'mission',
    commandLabel: 'Custom CSV Drone Show',
    statusLabel: 'Custom CSV Drone Show',
    shortLabel: 'Custom CSV Drone Show',
    statusClass: 'mission-performance',
    description: 'Replay the active custom protocol CSV relative to each launch point.',
    missionPickerOrder: 20,
  },
  {
    key: 'SWARM_TRAJECTORY',
    kind: 'mission',
    commandLabel: 'Swarm Trajectory',
    statusLabel: 'Swarm Trajectory',
    shortLabel: 'Swarm Trajectory',
    statusClass: 'mission-performance',
    description: 'Dispatch the processed leader-route package across the selected cluster.',
    missionPickerOrder: 40,
  },
  {
    key: 'QUICKSCOUT',
    kind: 'mission',
    commandLabel: 'QuickScout',
    statusLabel: 'QuickScout',
    shortLabel: 'QuickScout',
    statusClass: 'mission-performance',
    description: 'Run the prepared QuickScout search-and-rescue mission.',
  },
  {
    key: 'REBOOT_FC',
    kind: 'action',
    commandLabel: 'Reboot Flight Controls',
    statusLabel: 'Reboot Flight Controls',
    shortLabel: 'Reboot PX4',
    statusClass: 'mission-system',
    description: 'Restart PX4 and flight-control services.',
  },
  {
    key: 'REBOOT_SYS',
    kind: 'action',
    commandLabel: 'Reboot Companion Computer',
    statusLabel: 'Reboot Companion Computer',
    shortLabel: 'Reboot System',
    statusClass: 'mission-system',
    description: 'Restart the companion computer or container.',
  },
  {
    key: 'TEST_LED',
    kind: 'action',
    commandLabel: 'Test Light Show',
    statusLabel: 'Test Light Show',
    shortLabel: 'LED Test',
    statusClass: 'mission-test',
    description: 'Run the light-pattern test.',
  },
  {
    key: 'TAKE_OFF',
    kind: 'action',
    commandLabel: 'Take Off',
    statusLabel: 'Take Off',
    shortLabel: 'Take Off',
    statusClass: 'mission-flight',
    description: 'Climb to the configured takeoff altitude.',
  },
  {
    key: 'TEST',
    kind: 'action',
    commandLabel: 'Arm/Disarm Ground Test',
    statusLabel: 'Arm/Disarm Ground Test',
    shortLabel: 'Arm/Disarm Test',
    statusClass: 'mission-test',
    description: 'Physically arm motors for about 3 seconds, then disarm. Secure the aircraft and remove propellers.',
  },
  {
    key: 'LAND',
    kind: 'action',
    commandLabel: 'Land',
    statusLabel: 'Land',
    shortLabel: 'Land',
    statusClass: 'mission-flight',
    description: 'Land the selected aircraft now.',
  },
  {
    key: 'HOLD',
    kind: 'action',
    commandLabel: 'Hold Position',
    statusLabel: 'Hold Position',
    shortLabel: 'Hold Position',
    statusClass: 'mission-flight',
    description: 'Keep an already-airborne aircraft at its current position. This does not launch.',
  },
  {
    key: 'UPDATE_CODE',
    kind: 'action',
    commandLabel: 'Update Code',
    statusLabel: 'Update Code',
    shortLabel: 'Update Code',
    statusClass: 'mission-system',
    description: 'Install the configured source revision through the tracked update workflow.',
  },
  {
    key: 'RETURN_RTL',
    kind: 'action',
    commandLabel: 'Return to Launch',
    statusLabel: 'Return to Launch',
    shortLabel: 'RTL',
    statusClass: 'mission-flight',
    description: 'Return the selected aircraft to launch.',
  },
  {
    key: 'KILL_TERMINATE',
    kind: 'action',
    commandLabel: 'Emergency Kill',
    statusLabel: 'Emergency Kill',
    shortLabel: 'Kill',
    statusClass: 'mission-emergency',
    description: 'Emergency motor stop.',
  },
  {
    key: 'HOVER_TEST',
    kind: 'action',
    commandLabel: 'Automated Hover Flight',
    statusLabel: 'Automated Hover Flight',
    shortLabel: 'Auto Hover Flight',
    statusClass: 'mission-test',
    description: 'Automatically take off, fly the hover-test trajectory, then land. This is not Hold.',
  },
  {
    key: 'PRECISION_MOVE',
    kind: 'action',
    commandLabel: 'Precision Move',
    statusLabel: 'Precision Move',
    shortLabel: 'Precision Move',
    statusClass: 'mission-flight',
    description: 'Move a local offset from the current state, then hold.',
  },
  {
    key: 'UNKNOWN',
    kind: 'status',
    commandLabel: 'Unknown Command',
    statusLabel: 'Unknown Mission',
    shortLabel: 'Unknown',
    statusClass: 'mission-default',
    description: 'The node reported an unrecognized mission value.',
  },
];

const missionValueByKey = Object.freeze(Object.fromEntries(
  missionIdentities.map(({ key, value }) => [key, value]),
));
const identityKeys = missionIdentities.map(({ key }) => key);
const identityValues = missionIdentities.map(({ value }) => value);
const metadataKeys = metadataEntries.map(({ key }) => key);
const missingMetadata = missionIdentities
  .map(({ key }) => key)
  .filter((key) => !metadataKeys.includes(key));
const unknownMetadata = metadataKeys.filter((key) => !(key in missionValueByKey));
const hasDuplicateIdentity = new Set(identityKeys).size !== identityKeys.length
  || new Set(identityValues).size !== identityValues.length;
const hasDuplicateMetadata = new Set(metadataKeys).size !== metadataKeys.length;

if (
  hasDuplicateIdentity
  || hasDuplicateMetadata
  || missingMetadata.length > 0
  || unknownMetadata.length > 0
) {
  throw new Error(
    `Mission catalog metadata mismatch (duplicate identity: ${hasDuplicateIdentity}; duplicate metadata: ${hasDuplicateMetadata}; missing: ${missingMetadata.join(', ') || 'none'}; unknown: ${unknownMetadata.join(', ') || 'none'})`,
  );
}

const entries = metadataEntries.map((entry) => ({
  ...entry,
  value: missionValueByKey[entry.key],
}));

export const COMMAND_CATALOG = Object.freeze(entries.map((entry) => Object.freeze(entry)));

export const COMMAND_METADATA_BY_KEY = Object.freeze(COMMAND_CATALOG.reduce((result, entry) => {
  result[entry.key] = entry;
  return result;
}, {}));

export const COMMAND_METADATA_BY_VALUE = Object.freeze(COMMAND_CATALOG.reduce((result, entry) => {
  result[entry.value] = entry;
  return result;
}, {}));

export const getCommandMetadata = (commandValue) => {
  if (typeof commandValue === 'number') {
    return COMMAND_METADATA_BY_VALUE[commandValue] || null;
  }

  if (typeof commandValue !== 'string') {
    return null;
  }

  const normalized = commandValue.trim();
  if (!normalized) {
    return null;
  }

  if (/^\d+$/.test(normalized)) {
    return COMMAND_METADATA_BY_VALUE[Number(normalized)] || null;
  }

  return COMMAND_METADATA_BY_KEY[normalized] || null;
};
