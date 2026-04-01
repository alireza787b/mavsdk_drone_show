import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import PropTypes from 'prop-types';

import { getActiveCommands, getRecentCommands } from '../services/droneApiService';
import { buildLifecycleSnapshotFromStatus } from '../utilities/commandLifecycleFeedback';

const CommandActivityContext = createContext(null);
const MAX_COMMAND_MONITORS = 8;

function sortCommandMonitors(monitors = []) {
  return [...monitors].sort((left, right) => {
    const leftPriority = left?.isTerminal || left?.trackingIssue ? 1 : 0;
    const rightPriority = right?.isTerminal || right?.trackingIssue ? 1 : 0;

    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return Number(right?.updatedAtMs || 0) - Number(left?.updatedAtMs || 0);
  });
}

function mergeSnapshots(previousMonitors, incomingSnapshots) {
  const normalizedSnapshots = (Array.isArray(incomingSnapshots) ? incomingSnapshots : [incomingSnapshots])
    .filter((snapshot) => snapshot?.commandId);

  if (normalizedSnapshots.length === 0) {
    return previousMonitors;
  }

  let next = [...previousMonitors];

  normalizedSnapshots.forEach((snapshot) => {
    const existing = next.find((item) => item.commandId === snapshot.commandId);
    if (existing && Number(existing.updatedAtMs || 0) > Number(snapshot.updatedAtMs || 0)) {
      return;
    }

    const merged = existing ? { ...existing, ...snapshot } : snapshot;
    next = [
      merged,
      ...next.filter((item) => item.commandId !== snapshot.commandId),
    ];
  });

  return sortCommandMonitors(next).slice(0, MAX_COMMAND_MONITORS);
}

export const useCommandActivity = () => {
  const context = useContext(CommandActivityContext);
  if (!context) {
    throw new Error('useCommandActivity must be used within a CommandActivityProvider');
  }
  return context;
};

export const CommandActivityProvider = ({ children }) => {
  const [commandMonitors, setCommandMonitors] = useState([]);

  const mergeCommandMonitors = useCallback((snapshots) => {
    setCommandMonitors((previous) => mergeSnapshots(previous, snapshots));
  }, []);

  const dismissCommandMonitor = useCallback((commandId) => {
    if (!commandId) {
      return;
    }

    setCommandMonitors((previous) => previous.filter((item) => item.commandId !== commandId));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const hydrateCommandMonitors = async () => {
      try {
        const [activeResponse, recentResponse] = await Promise.all([
          getActiveCommands(),
          getRecentCommands({ limit: MAX_COMMAND_MONITORS }),
        ]);

        if (cancelled) {
          return;
        }

        const seen = new Set();
        const hydratedSnapshots = [...(activeResponse?.commands || []), ...(recentResponse?.commands || [])]
          .filter((status) => {
            const commandId = status?.command_id;
            if (!commandId || seen.has(commandId)) {
              return false;
            }
            seen.add(commandId);
            return true;
          })
          .map((status) => buildLifecycleSnapshotFromStatus(status))
          .filter(Boolean);

        mergeCommandMonitors(hydratedSnapshots);
      } catch (error) {
        console.error('Failed to hydrate command monitors', error);
      }
    };

    hydrateCommandMonitors();

    return () => {
      cancelled = true;
    };
  }, [mergeCommandMonitors]);

  const sortedCommandMonitors = useMemo(
    () => sortCommandMonitors(commandMonitors),
    [commandMonitors],
  );
  const primaryMonitor = sortedCommandMonitors[0] || null;
  const recentCommandMonitors = sortedCommandMonitors.slice(1, 5);

  const commandLifecycleCallbacks = useMemo(() => ({
    onCommandAccepted: mergeCommandMonitors,
    onStatusUpdate: mergeCommandMonitors,
    onTrackingComplete: mergeCommandMonitors,
    onTrackingUnavailable: mergeCommandMonitors,
  }), [mergeCommandMonitors]);

  const value = useMemo(() => ({
    commandMonitors: sortedCommandMonitors,
    primaryMonitor,
    recentCommandMonitors,
    mergeCommandMonitors,
    dismissCommandMonitor,
    commandLifecycleCallbacks,
  }), [
    commandLifecycleCallbacks,
    dismissCommandMonitor,
    mergeCommandMonitors,
    primaryMonitor,
    recentCommandMonitors,
    sortedCommandMonitors,
  ]);

  return (
    <CommandActivityContext.Provider value={value}>
      {children}
    </CommandActivityContext.Provider>
  );
};

CommandActivityProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export default CommandActivityContext;
