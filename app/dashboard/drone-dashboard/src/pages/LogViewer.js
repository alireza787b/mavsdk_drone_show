// src/pages/LogViewer.js
/**
 * Log Viewer — real-time and historical log viewing for drone operations.
 * Operations mode (default): WARNING+, health drill-down, focused live feed.
 * Developer mode: all levels, component tree, time controls, scope switching.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { toast } from 'react-toastify';
import { useTheme } from '../hooks/useTheme';
import useLogStream from '../hooks/useLogStream';
import {
  getConfiguredDrones,
  getDroneSessionContent,
  getDroneSessions,
  getHeartbeats,
  getSessionContent,
  getSessions,
  getSources,
} from '../services/logService';
import {
  DEV_DEFAULT_LEVEL,
  HEALTH_POLL_INTERVAL_MS,
  LIVE_TIME_WINDOWS,
  MODES,
  OPS_DEFAULT_LEVEL,
} from '../constants/logConstants';
import {
  applySeverityFocus,
  buildComponentCatalog,
  filterEntriesByAbsoluteTimeRange,
  filterEntriesByRelativeWindow,
} from '../utilities/logViewerUtils';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';

import LogViewerToolbar from '../components/logs/LogViewerToolbar';
import LogActiveFilters from '../components/logs/LogActiveFilters';
import LogHealthBar from '../components/logs/LogHealthBar';
import LogTable from '../components/logs/LogTable';
import LogSourceTree from '../components/logs/LogSourceTree';
import LogExportDialog from '../components/logs/LogExportDialog';
import OnboardUlogDialog from '../components/logs/OnboardUlogDialog';
import IdentityDoctrineStrip from '../components/IdentityDoctrineStrip';

import '../styles/LogViewer.css';

const normalizeDroneOption = (drone) => {
  const hwId = Number(drone?.hw_id);
  if (!Number.isFinite(hwId)) {
    return null;
  }

  return {
    hw_id: hwId,
    pos_id: drone?.pos_id ?? hwId,
    label: formatCompactDroneIdentity(drone?.pos_id, hwId, `H${hwId}`),
  };
};

const formatRangeValue = (value) => {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
};

const LogViewer = () => {
  const { isDark } = useTheme();

  // UI state
  const [mode, setMode] = useState(MODES.OPS);
  const [level, setLevel] = useState(OPS_DEFAULT_LEVEL);
  const [component, setComponent] = useState(null);
  const [paused, setPaused] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showExport, setShowExport] = useState(false);
  const [showOnboardUlog, setShowOnboardUlog] = useState(false);
  const [scopeDroneId, setScopeDroneId] = useState(null);
  const [severityFocus, setSeverityFocus] = useState(null);
  const [liveWindow, setLiveWindow] = useState('all');
  const [timeStart, setTimeStart] = useState('');
  const [timeEnd, setTimeEnd] = useState('');

  // Fleet metadata
  const [fleet, setFleet] = useState([]);
  const [onlineDroneIds, setOnlineDroneIds] = useState(new Set());
  const [gcsOnline, setGcsOnline] = useState(false);
  const [gcsSources, setGcsSources] = useState({});

  // Session state
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [selectedSession, setSelectedSession] = useState(null);
  const [historicalEntries, setHistoricalEntries] = useState([]);

  // SSE stream (disabled when viewing historical session; paused freezes display but keeps connection)
  const streamEnabled = !selectedSession;
  const { entries: liveEntries, connected, error: streamError, clear } = useLogStream({
    level,
    enabled: streamEnabled,
    paused,
    droneId: scopeDroneId,
  });

  useEffect(() => {
    if (!streamError) {
      return;
    }
    toast.warning(streamError);
  }, [streamError]);

  useEffect(() => {
    let mounted = true;

    const fetchFleetSnapshot = async () => {
      try {
        const [configData, heartbeatData, sourcesData] = await Promise.all([
          getConfiguredDrones(),
          getHeartbeats(),
          getSources(),
        ]);

        if (!mounted) {
          return;
        }

        const configuredDrones = (configData || [])
          .map(normalizeDroneOption)
          .filter(Boolean)
          .sort((left, right) => left.hw_id - right.hw_id);

        const onlineIds = new Set(
          (heartbeatData?.heartbeats || [])
            .filter((heartbeat) => heartbeat?.online)
            .map((heartbeat) => String(heartbeat.hw_id)),
        );

        setFleet(configuredDrones);
        setOnlineDroneIds(onlineIds);
        setGcsSources(sourcesData?.components || {});
        setGcsOnline(true);
      } catch {
        if (mounted) {
          setGcsOnline(false);
        }
      }
    };

    fetchFleetSnapshot();
    const timer = setInterval(fetchFleetSnapshot, HEALTH_POLL_INTERVAL_MS);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  const fetchSessions = useCallback(async (showErrors = false) => {
    setSessionsLoading(true);
    try {
      const data = scopeDroneId != null
        ? await getDroneSessions(scopeDroneId)
        : await getSessions();
      setSessions(data.sessions || []);
    } catch (error) {
      setSessions([]);
      if (showErrors) {
        const scopeLabel = scopeDroneId != null ? `drone #${scopeDroneId}` : 'GCS';
        toast.error(`Failed to load ${scopeLabel} sessions: ${error.message}`);
      }
    } finally {
      setSessionsLoading(false);
    }
  }, [scopeDroneId]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  useEffect(() => {
    setSelectedSession(null);
    setHistoricalEntries([]);
    setPaused(false);
    setComponent(null);
    setSeverityFocus(null);
    setSearchQuery('');
    setTimeStart('');
    setTimeEnd('');
    setShowExport(false);
    setShowOnboardUlog(false);
  }, [scopeDroneId]);

  useEffect(() => {
    if (!selectedSession) {
      setHistoricalEntries([]);
      return;
    }

    let mounted = true;

    const loadSession = async () => {
      try {
        const data = scopeDroneId != null
          ? await getDroneSessionContent(scopeDroneId, selectedSession, { level })
          : await getSessionContent(selectedSession, { level });

        const lines = (data.lines || []).map((line, idx) => ({ ...line, _id: `hist_${idx}` }));
        if (mounted) {
          setHistoricalEntries(lines);
        }
      } catch (error) {
        if (mounted) {
          toast.error(`Failed to load session: ${error.message}`);
        }
      }
    };

    loadSession();
    return () => {
      mounted = false;
    };
  }, [selectedSession, level, scopeDroneId]);

  const handleModeChange = useCallback((newMode) => {
    setMode(newMode);
    setSeverityFocus(null);

    if (newMode === MODES.OPS) {
      setLevel(OPS_DEFAULT_LEVEL);
      setSearchQuery('');
      setComponent(null);
    } else {
      setLevel(DEV_DEFAULT_LEVEL);
    }
  }, []);

  const handleSessionSelect = useCallback((sessionId) => {
    setSelectedSession(sessionId);
    setPaused(false);
    setSeverityFocus(null);
    setTimeStart('');
    setTimeEnd('');
  }, []);

  const handleClearEntries = useCallback(() => {
    clear();
  }, [clear]);

  const clearAllFilters = useCallback(() => {
    setLevel(mode === MODES.OPS ? OPS_DEFAULT_LEVEL : DEV_DEFAULT_LEVEL);
    setComponent(null);
    setSearchQuery('');
    setSeverityFocus(null);
    setTimeStart('');
    setTimeEnd('');
    setLiveWindow('all');
  }, [mode]);

  const liveWindowDuration = useMemo(() => (
    LIVE_TIME_WINDOWS.find((window) => window.value === liveWindow)?.durationMs ?? null
  ), [liveWindow]);

  const baseEntries = selectedSession ? historicalEntries : liveEntries;

  const timeScopedEntries = useMemo(() => {
    if (selectedSession) {
      return filterEntriesByAbsoluteTimeRange(baseEntries, timeStart, timeEnd);
    }

    return filterEntriesByRelativeWindow(baseEntries, liveWindowDuration);
  }, [baseEntries, selectedSession, timeStart, timeEnd, liveWindowDuration]);

  const availableComponents = useMemo(() => (
    buildComponentCatalog(timeScopedEntries, scopeDroneId == null ? gcsSources : undefined)
  ), [timeScopedEntries, scopeDroneId, gcsSources]);

  const componentScopedEntries = useMemo(() => (
    component
      ? timeScopedEntries.filter((entry) => entry.component === component)
      : timeScopedEntries
  ), [timeScopedEntries, component]);

  const displayedEntries = useMemo(() => (
    applySeverityFocus(componentScopedEntries, severityFocus)
  ), [componentScopedEntries, severityFocus]);

  const onlineDroneCount = useMemo(() => (
    fleet.filter((drone) => onlineDroneIds.has(String(drone.hw_id))).length
  ), [fleet, onlineDroneIds]);

  const selectedScope = useMemo(
    () => fleet.find((drone) => String(drone.hw_id) === String(scopeDroneId)) || null,
    [fleet, scopeDroneId],
  );

  const scopeLabel = scopeDroneId != null
    ? selectedScope?.label || `H${scopeDroneId}`
    : 'GCS';
  const defaultLevel = mode === MODES.OPS ? OPS_DEFAULT_LEVEL : DEV_DEFAULT_LEVEL;

  const activeFilters = useMemo(() => {
    const filters = [];

    if (level !== defaultLevel) {
      filters.push({
        key: 'level',
        label: level ? `Level: ${level}+` : 'Level: All Levels',
        onRemove: () => setLevel(defaultLevel),
      });
    }

    if (component) {
      filters.push({
        key: 'component',
        label: `Component: ${component}`,
        onRemove: () => setComponent(null),
      });
    }

    if (severityFocus === 'warnings') {
      filters.push({
        key: 'severity',
        label: 'Warnings Only',
        onRemove: () => setSeverityFocus(null),
      });
    }

    if (severityFocus === 'errors') {
      filters.push({
        key: 'severity',
        label: 'Errors Only',
        onRemove: () => setSeverityFocus(null),
      });
    }

    if (searchQuery) {
      filters.push({
        key: 'search',
        label: `Search: ${searchQuery}`,
        onRemove: () => setSearchQuery(''),
      });
    }

    if (!selectedSession && liveWindow !== 'all') {
      const windowLabel = LIVE_TIME_WINDOWS.find((window) => window.value === liveWindow)?.label || liveWindow;
      filters.push({
        key: 'liveWindow',
        label: `Window: ${windowLabel}`,
        onRemove: () => setLiveWindow('all'),
      });
    }

    if (selectedSession && timeStart) {
      filters.push({
        key: 'timeStart',
        label: `From: ${formatRangeValue(timeStart)}`,
        onRemove: () => setTimeStart(''),
      });
    }

    if (selectedSession && timeEnd) {
      filters.push({
        key: 'timeEnd',
        label: `To: ${formatRangeValue(timeEnd)}`,
        onRemove: () => setTimeEnd(''),
      });
    }

    return filters;
  }, [component, defaultLevel, level, liveWindow, searchQuery, selectedSession, severityFocus, timeEnd, timeStart]);

  const emptyState = useMemo(() => {
    if (displayedEntries.length > 0) {
      return {
        title: '',
        detail: '',
      };
    }

    if (activeFilters.length > 0 && componentScopedEntries.length === 0) {
      return {
        title: 'No logs match the current filters',
        detail: 'Clear one or more filters to widen the view.',
      };
    }

    if (selectedSession) {
      return {
        title: 'No logs in this session view',
        detail: 'This session has no entries for the current scope or level selection.',
      };
    }

    if (scopeDroneId != null) {
      return {
        title: `Waiting for live logs from ${scopeLabel}`,
        detail: 'If the drone is online but stays quiet, check that the drone-side service is running and producing logs.',
      };
    }

    return {
      title: 'Waiting for live GCS logs',
      detail: 'The viewer is connected. New log entries will appear here as events are emitted.',
    };
  }, [activeFilters.length, componentScopedEntries.length, displayedEntries.length, scopeDroneId, scopeLabel, selectedSession]);

  return (
    <div className={`log-viewer-page ${isDark ? 'dark' : 'light'}`}>
      <IdentityDoctrineStrip surface="log-viewer" />
      <LogViewerToolbar
        mode={mode}
        onModeChange={handleModeChange}
        level={level}
        onLevelChange={setLevel}
        paused={paused}
        onTogglePause={() => setPaused((current) => !current)}
        connected={connected}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        sessions={sessions}
        selectedSession={selectedSession}
        onSessionSelect={handleSessionSelect}
        sessionsLoading={sessionsLoading}
        onExportOpen={async () => {
          await fetchSessions(true);
          setShowExport(true);
        }}
        onOnboardUlogOpen={() => setShowOnboardUlog(true)}
        onClear={handleClearEntries}
        scopeDroneId={scopeDroneId}
        scopeOptions={fleet}
        onScopeChange={setScopeDroneId}
        liveWindow={liveWindow}
        onLiveWindowChange={setLiveWindow}
        timeStart={timeStart}
        onTimeStartChange={setTimeStart}
        timeEnd={timeEnd}
        onTimeEndChange={setTimeEnd}
        onClearTimeRange={() => {
          setTimeStart('');
          setTimeEnd('');
        }}
      />

      <LogHealthBar
        entries={componentScopedEntries}
        displayedCount={displayedEntries.length}
        gcsOnline={gcsOnline}
        fleetCount={fleet.length}
        onlineDroneCount={onlineDroneCount}
        severityFocus={severityFocus}
        onSeverityFocusChange={setSeverityFocus}
      />

      <div className="log-viewer-context">
        <span className="log-context-pill">{scopeLabel}</span>
        {selectedSession ? (
          <span className="log-context-note">Historical session view</span>
        ) : (
          <span className="log-context-note">Live stream view</span>
        )}
        <span className="log-context-note">Session timestamps shown in UTC</span>
      </div>

      <LogActiveFilters
        filters={activeFilters}
        onClearAll={clearAllFilters}
      />

      <div style={{ display: 'flex', flex: 1, gap: 'var(--spacing-sm)', overflow: 'hidden' }}>
        {mode === MODES.DEV && (
          <div style={{ width: 220, flexShrink: 0 }}>
            <LogSourceTree
              components={availableComponents}
              selectedComponent={component}
              onSelect={setComponent}
            />
          </div>
        )}

        <LogTable
          entries={displayedEntries}
          autoScroll={!selectedSession}
          searchQuery={searchQuery}
          emptyStateTitle={emptyState.title}
          emptyStateDetail={emptyState.detail}
          onClearFilters={clearAllFilters}
          canClearFilters={activeFilters.length > 0}
        />
      </div>

      {showExport && (
        <LogExportDialog
          sessions={sessions}
          droneId={scopeDroneId}
          scopeLabel={scopeLabel}
          onClose={() => setShowExport(false)}
        />
      )}

      {showOnboardUlog && scopeDroneId != null && (
        <OnboardUlogDialog
          open={showOnboardUlog}
          droneId={scopeDroneId}
          scopeLabel={scopeLabel}
          onClose={() => setShowOnboardUlog(false)}
        />
      )}
    </div>
  );
};

export default LogViewer;
