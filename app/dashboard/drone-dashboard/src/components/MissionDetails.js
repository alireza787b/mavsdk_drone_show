import React from 'react';
import { Link } from 'react-router-dom';
import {
  FaCheckCircle,
  FaExclamationTriangle,
  FaGlobeAmericas,
  FaInfoCircle,
  FaLocationArrow,
} from 'react-icons/fa';
import '../styles/MissionDetails.css';
import { DRONE_MISSION_IMAGES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import MissionReadinessCard from './MissionReadinessCard';
import useFetch from '../hooks/useFetch';
import useSwarmClusterStatus from '../hooks/useSwarmClusterStatus';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import {
  buildCommandSchedule,
  COMMAND_SCHEDULE_MODES,
} from '../utilities/commandScheduling';
import { getMissionScheduleDoctrine } from '../utilities/commandExecutionPolicy';
import { buildSwarmTrajectoryLaunchReadiness } from '../utilities/swarmTrajectoryLaunchReadiness';
import {
  formatSwarmTrajectoryAltitudeEnvelope,
  formatSwarmTrajectoryMissionSeconds,
} from '../utilities/swarmTrajectoryPackageStats';

const MissionDetails = ({
  missionType,
  icon,
  profile = '',
  label,
  description,
  targetMode = 'all',
  selectedDrones = [],
  targetDroneIds = [],
  targetSummaryLabel = 'All targeted drones',
  scheduleMode,
  timeDelay,
  selectedDateTime,
  onTimeDelayChange,
  onTimePickerChange,
  onScheduleModeChange,
  autoGlobalOrigin,
  onAutoGlobalOriginChange,
  useGlobalSetpoints,
  onUseGlobalSetpointsChange,
  delayPresets = [],
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
  onSend,
  onBack,
}) => {
  const missionImageSrc = DRONE_MISSION_IMAGES[missionType];
  const schedulePreview = buildCommandSchedule({
    scheduleMode,
    timeDelay,
    selectedDateTime,
    referenceNowMs,
  });
  
  // Check origin status for auto global origin correction mode
  const { data: originData } = useFetch(GCS_ROUTE_KEYS.origin);
  const isOriginSet = originData && 
    originData.lat !== undefined && 
    originData.lon !== undefined && 
    originData.lat !== null && 
    originData.lon !== null &&
    originData.lat !== '' && 
    originData.lon !== '';
  
  // Fetch deviation data when auto correction is enabled and origin is set
  const shouldFetchDeviations = isOriginSet && autoGlobalOrigin && useGlobalSetpoints;
  const { data: deviationData } = useFetch(GCS_ROUTE_KEYS.positionDeviations, shouldFetchDeviations ? 5000 : null);
  
  // Only show hints for DRONE_SHOW_FROM_CSV mission type
  const showModeHints = missionType === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV;
  const customShowHints = missionType === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW;
  const smartSwarmHints = missionType === DRONE_MISSION_TYPES.SMART_SWARM;
  const swarmTrajectoryHints = missionType === DRONE_MISSION_TYPES.SWARM_TRAJECTORY;
  const { data: showInfo, error: showInfoError, loading: showInfoLoading } = useFetch(
    showModeHints ? GCS_ROUTE_KEYS.showInfo : null
  );
  const { data: customShowInfo, error: customShowError, loading: customShowLoading } = useFetch(
    customShowHints ? GCS_ROUTE_KEYS.customShowInfo : null
  );
  const { data: smartSwarmInfo, error: smartSwarmError, loading: smartSwarmLoading } = useFetch(
    smartSwarmHints ? GCS_ROUTE_KEYS.swarmLeaders : null
  );
  const {
    data: swarmTrajectoryStatus,
    error: swarmTrajectoryStatusError,
    loading: swarmTrajectoryStatusLoading,
    refresh: refreshSwarmTrajectoryStatus,
  } = useSwarmClusterStatus({
    enabled: swarmTrajectoryHints,
    intervalMs: 5000,
    refreshTrigger: 0,
  });
  const swarmTrajectoryReadiness = buildSwarmTrajectoryLaunchReadiness({
    clusterStatus: swarmTrajectoryStatus,
    loading: swarmTrajectoryStatusLoading,
    error: swarmTrajectoryStatusError,
    targetMode,
    selectedDrones,
    targetDroneIds,
  });
  const swarmTrajectoryBlockers = swarmTrajectoryReadiness.blockers;
  const swarmTrajectoryWarnings = swarmTrajectoryReadiness.warnings;
  const swarmTrajectorySummary = swarmTrajectoryReadiness.summary;
  
  // Extract deviation summary
  const deviationSummary = deviationData?.summary || null;
  const deviations = deviationData?.deviations || {};
  
  // Thresholds for placement status (matches backend)
  const thresholdWarning = 3.0;  // acceptable_deviation
  const thresholdError = 7.5;    // threshold_warning * 2.5
  
  // Analyze warnings to categorize them
  const analyzeWarnings = () => {
    if (!deviationSummary || !deviationSummary.warnings) {
      return { placementWarnings: 0, gpsWarnings: 0, warningDetails: [] };
    }
    
    const placementWarnings = [];
    const gpsWarnings = [];
    const warningDetails = [];
    
    Object.entries(deviations).forEach(([hw_id, dev]) => {
      if (dev.status === 'warning' || dev.status === 'error') {
        const devValue = dev.deviation?.horizontal || 0;
        const message = dev.message || '';
        
        // Check if warning is due to GPS quality or placement
        const messageLower = message.toLowerCase();
        const isGpsWarning = messageLower.includes('gps') || 
                             messageLower.includes('poor') ||
                             messageLower.includes('quality') ||
                             messageLower.includes('satellite') ||
                             messageLower.includes('hdop');
        
        // If deviation is excellent (<= threshold) but status is warning, it's GPS related
        const isExcellentPlacement = devValue <= thresholdWarning;
        
        if (isGpsWarning || (isExcellentPlacement && dev.status === 'warning')) {
          gpsWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'gps',
            message: message || 'GPS quality issue',
            deviation: devValue
          });
        } else if (devValue > thresholdWarning) {
          // Placement warning - deviation exceeds threshold
          placementWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'placement',
            message: message || `Deviation ${devValue.toFixed(2)}m exceeds threshold`,
            deviation: devValue
          });
        } else {
          // Unknown warning type, but deviation is good - treat as GPS
          gpsWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'gps',
            message: message || 'Non-placement issue detected',
            deviation: devValue
          });
        }
      }
    });
    
    return {
      placementWarnings: placementWarnings.length,
      gpsWarnings: gpsWarnings.length,
      warningDetails
    };
  };
  
  const warningAnalysis = analyzeWarnings();
  
  // Get placement status based on actual deviation
  const getPlacementStatus = () => {
    if (!deviationSummary || !deviationSummary.worst_deviation) return null;
    const worst = deviationSummary.worst_deviation;
    
    if (worst <= thresholdWarning) {
      return {
        status: 'excellent',
        color: 'var(--color-success)',
        surface: 'var(--color-success-light)',
        icon: <FaCheckCircle aria-hidden="true" />,
        text: 'Nominal'
      };
    } else if (worst <= thresholdError) {
      return {
        status: 'warning',
        color: 'var(--color-warning)',
        surface: 'var(--color-warning-light)',
        icon: <FaExclamationTriangle aria-hidden="true" />,
        text: 'Review'
      };
    } else {
      return {
        status: 'error',
        color: 'var(--color-danger)',
        surface: 'var(--color-danger-light)',
        icon: <FaExclamationTriangle aria-hidden="true" />,
        text: 'Blocked'
      };
    }
  };
  
  const placementStatus = getPlacementStatus();
  const showImported = Boolean(showInfo && showInfo.drone_count > 0);
  const customShowReady = Boolean(customShowInfo && customShowInfo.exists);
  const droneShowBlockers = [];
  const droneShowWarnings = [];
  const customShowBlockers = [];
  const customShowWarnings = [];
  const smartSwarmBlockers = [];
  const smartSwarmWarnings = [];
  const swarmTrajectoryWarningsList = [...swarmTrajectoryWarnings];
  const scheduleDoctrine = getMissionScheduleDoctrine(missionType);

  if (showModeHints && showInfoLoading) {
    droneShowBlockers.push('Verifying imported Drone Show package...');
  }

  if (showModeHints && !showInfoLoading) {
    if (!showImported) {
      droneShowBlockers.push('No processed Drone Show is loaded. Import a SkyBrush ZIP on the Show Design page first.');
    }

    if (showInfoError && !showImported) {
      droneShowWarnings.push('Show metadata could not be verified from the backend.');
    }

    if (useGlobalSetpoints && autoGlobalOrigin && !isOriginSet) {
      droneShowBlockers.push('Auto Global Launch Corrector requires a configured shared origin.');
    }

    if (useGlobalSetpoints && autoGlobalOrigin && isOriginSet && deviationSummary) {
      if (deviationSummary.online === 0) {
        droneShowBlockers.push('No live drone telemetry is available for launch-position verification.');
      }
      if (deviationSummary.errors > 0) {
        droneShowBlockers.push('Critical launch-position errors must be resolved before launch.');
      }
      if (warningAnalysis.placementWarnings > 0) {
        droneShowWarnings.push('Some drones still have placement warnings. Review Mission Config before launch.');
      }
      if (warningAnalysis.gpsWarnings > 0) {
        droneShowWarnings.push('Some drones have GPS quality warnings. Confirm these are acceptable before launch.');
      }
    }

    if (useGlobalSetpoints && !autoGlobalOrigin) {
      droneShowWarnings.push('GLOBAL manual mode assumes operators placed every drone exactly on its assigned launch point.');
    }
  }

  if (customShowHints && customShowLoading) {
    customShowBlockers.push('Verifying active custom CSV package...');
  }

  if (customShowHints && !customShowLoading) {
    if (!customShowReady) {
      customShowBlockers.push('No active custom CSV is loaded. Open Custom Show and upload one ready-to-execute protocol CSV first.');
    }

    if (customShowError && !customShowReady) {
      customShowWarnings.push('Custom CSV metadata could not be verified from the backend.');
    }

    if (customShowReady && !customShowInfo.preview_exists) {
      customShowWarnings.push('Preview image is missing. Re-upload the custom CSV from Custom Show if operators need a visual cross-check.');
    }
  }

  if (smartSwarmHints) {
    const leaders = smartSwarmInfo?.leaders || [];
    const followerDetails = smartSwarmInfo?.follower_details || {};
    const totalFollowers = Object.values(followerDetails).reduce(
      (count, followers) => count + (Array.isArray(followers) ? followers.length : 0),
      0,
    );

    if (smartSwarmLoading) {
      smartSwarmWarnings.push('Loading Smart Swarm topology snapshot...');
    }

    if (!smartSwarmLoading && leaders.length === 0) {
      smartSwarmWarnings.push('No Smart Swarm topology is currently published from Swarm Design.');
    }

    if (smartSwarmError && leaders.length === 0) {
      smartSwarmWarnings.push('Smart Swarm topology could not be verified from the backend.');
    }

    if (!smartSwarmLoading && leaders.length > 0 && totalFollowers === 0) {
      smartSwarmWarnings.push('The current topology has leaders but no follower links.');
    }
  }

  if (
    swarmTrajectoryHints
    && swarmTrajectoryReadiness.canLaunch
    && swarmTrajectorySummary.session.exists
    && swarmTrajectorySummary.readyClusterCount > 0
    && swarmTrajectorySummary.advisoryCount === 0
  ) {
    swarmTrajectoryWarningsList.push('Processed package is active. Confirm the final plots before launch.');
  }

  const missionBlockers = showModeHints
    ? droneShowBlockers
    : customShowHints
      ? customShowBlockers
      : smartSwarmHints
        ? smartSwarmBlockers
        : swarmTrajectoryHints
          ? swarmTrajectoryBlockers
          : [];
  const missionWarnings = showModeHints
    ? droneShowWarnings
    : customShowHints
      ? customShowWarnings
      : smartSwarmHints
        ? smartSwarmWarnings
        : swarmTrajectoryHints
          ? swarmTrajectoryWarningsList
          : [];
  const canSendMission = missionBlockers.length === 0 && !schedulePreview.error;
  const missionStatusIcon = canSendMission
    ? <FaCheckCircle aria-hidden="true" />
    : <FaExclamationTriangle aria-hidden="true" />;
  
  // Find drones with worst deviation (with tolerance for floating point comparison)
  const getWorstDeviationDrones = () => {
    if (!deviationSummary || !deviationSummary.worst_deviation) return [];
    const worst = deviationSummary.worst_deviation;
    const tolerance = 0.01; // 1cm tolerance for floating point comparison
    return Object.entries(deviations)
      .filter(([_, dev]) => {
        const devValue = dev.deviation?.horizontal;
        return devValue !== undefined && devValue !== null && 
               Math.abs(devValue - worst) < tolerance;
      })
      .map(([hw_id, _]) => hw_id)
      .sort((a, b) => parseInt(a) - parseInt(b)); // Sort by hw_id numerically
  };
  
  const worstDeviationDrones = getWorstDeviationDrones();
  
  // Format origin coordinates
  const formatOrigin = () => {
    if (!isOriginSet) return null;
    const lat = parseFloat(originData.lat).toFixed(6);
    const lon = parseFloat(originData.lon).toFixed(6);
    return `${lat}°, ${lon}°`;
  };

  const renderOperatorNotes = (summaryLabel, items) => (
    <details className="mission-operator-notes">
      <summary>
        <span>{summaryLabel}</span>
        <small>Expand notes</small>
      </summary>
      <ul>
        {items.map((item, index) => (
          <li key={`${summaryLabel}-${index}`}>{item}</li>
        ))}
      </ul>
    </details>
  );

  const renderIssueDigest = (summaryLabel, items, tone = 'warning') => {
    if (!items || items.length === 0) {
      return null;
    }

    const itemLabel = tone === 'danger'
      ? `blocker${items.length === 1 ? '' : 's'}`
      : items.length === 1 ? 'advisory' : 'advisories';

    return (
      <details className={`mission-issue-digest mission-issue-digest--${tone}`} open={tone === 'danger'}>
        <summary>
          <span>{summaryLabel}</span>
          <small>{items.length} {itemLabel}</small>
        </summary>
        <ul>
          {items.map((item) => (
            <li key={`${summaryLabel}-${item}`}>{item}</li>
          ))}
        </ul>
      </details>
    );
  };

  const renderSnapshot = ({
    title,
    facts,
    blockers = [],
    warnings = [],
    reference = null,
    notes = null,
  }) => {
    const hasBlockers = blockers.length > 0;
    const hasWarnings = warnings.length > 0;
    const postureLabel = hasBlockers
      ? 'Blocked'
      : hasWarnings
        ? 'Review advisories'
        : 'Ready';

    return (
      <div className={`origin-warning ${hasBlockers ? 'origin-missing' : ''}`}>
        <div className="warning-icon" aria-hidden="true">{missionStatusIcon}</div>
        <div className="warning-content">
          <strong>{title}</strong>
          <div className={`mission-health-strip ${hasBlockers ? 'mission-health-strip--danger' : hasWarnings ? 'mission-health-strip--warning' : 'mission-health-strip--good'}`}>
            <span>{postureLabel}</span>
          </div>
          <div className="origin-confirmation">
            {facts.map((fact) => (
              <div className="origin-info-row" key={`${title}-${fact.label}`}>
                <span className="origin-label">{fact.label}</span>
                <span className="origin-coords">{fact.value}</span>
              </div>
            ))}
          </div>
          {renderIssueDigest('Blockers to resolve', blockers, 'danger')}
          {renderIssueDigest('Operator advisories', warnings, 'warning')}
          {reference}
          {notes}
        </div>
      </div>
    );
  };

  const targetScopeSummary = targetSummaryLabel || (
    targetMode === 'selected'
      ? `${selectedDrones.length} selected drone${selectedDrones.length === 1 ? '' : 's'}`
      : targetMode === 'cluster'
        ? `${targetDroneIds.length} clustered drone${targetDroneIds.length === 1 ? '' : 's'}`
        : 'All targeted drones'
  );
  const scheduleModeSummary = scheduleMode === COMMAND_SCHEDULE_MODES.NOW
    ? 'Immediate'
    : scheduleMode === COMMAND_SCHEDULE_MODES.DELAY
      ? `+${timeDelay}s delay`
      : 'Exact UTC';
  const missionBriefItems = {
    [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: [
      'Runs the active processed SkyBrush package with shared fleet timing.',
      'Verify launch slots, origin truth, and control mode before dispatch.',
    ],
    [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: [
      'Replays the active custom CSV relative to each aircraft launch point.',
      'Confirm the active file and preview before dispatch.',
    ],
    [DRONE_MISSION_TYPES.SMART_SWARM]: [
      'Starts the published leader-follower topology from Swarm Design.',
      'Review leaders, followers, and override doctrine before launch.',
    ],
    [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: [
      'Dispatches the processed leader-route package across the current cluster scope.',
      'Review plots, timing, and cluster readiness before launch.',
    ],
  }[missionType] || [];

  return (
    <div className="mission-details">
      <div className="selected-mission-card">
        {profile && <div className="mission-profile-tag">{profile}</div>}
        <div className="mission-icon">{icon}</div>
        <div className="mission-name">{label}</div>
        <div className="mission-description">{description}</div>
        <div className="mission-meta-row">
          <span className="mission-meta-chip">{targetScopeSummary}</span>
          <span className="mission-meta-chip">{scheduleModeSummary}</span>
        </div>
      </div>

      {missionBriefItems.length > 0 && (
        <details className="mission-brief">
          <summary>
            <span>Mission brief</span>
            <small>Open doctrine and operator notes</small>
          </summary>
          <ul>
            {missionBriefItems.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}

      {/* Display mission-specific image */}
      {missionImageSrc && (
        <details className="mission-preview">
          <summary>
            <span>Preview plot</span>
            <small>Open the processed image</small>
          </summary>
          <img src={missionImageSrc} alt={label} className="mission-image" />
        </details>
      )}

      {/* Mode Selection: Local vs Global */}
      {showModeHints && (
        <div className="mode-selection-section">
          <h3 className="mode-selection-title">Control Mode</h3>
          <div className="mode-toggle-container">
            <label className={`mode-option ${!useGlobalSetpoints ? 'active' : ''}`}>
              <input
                type="radio"
                name="controlMode"
                checked={!useGlobalSetpoints}
                onChange={() => onUseGlobalSetpointsChange(false)}
                className="mode-radio"
              />
              <div className="mode-content">
                <span className="mode-icon" aria-hidden="true"><FaLocationArrow /></span>
                <span className="mode-label">LOCAL Mode</span>
                <span className="mode-description">Manual launch marks with local NED execution.</span>
              </div>
            </label>
            <label className={`mode-option ${useGlobalSetpoints ? 'active' : ''}`}>
              <input
                type="radio"
                name="controlMode"
                checked={useGlobalSetpoints}
                onChange={() => onUseGlobalSetpointsChange(true)}
                className="mode-radio"
              />
              <div className="mode-content">
                <span className="mode-icon" aria-hidden="true"><FaGlobeAmericas /></span>
                <span className="mode-label">GLOBAL Mode</span>
                <span className="mode-description">GPS-based launch positioning and tracking.</span>
              </div>
            </label>
          </div>
        </div>
      )}

      {/* Mode-specific hints and guidance */}
      {showModeHints && !useGlobalSetpoints && (
        <details className="mission-operator-notes mission-operator-notes--mode">
          <summary>
            <span><FaInfoCircle aria-hidden="true" /> Local Mode Operator Notes</span>
            <small>Manual launch placement and estimator assumptions</small>
          </summary>
          <ul>
            <li>Uses <strong>local NED coordinates</strong> relative to the launch position.</li>
            <li>Operators must place drones <strong>exactly</strong> on their assigned launch marks.</li>
            <li>The current replay path still depends on a valid launch and home reference before execution.</li>
            <li>Use this only after validating the PX4 local-estimator workflow for the deployment.</li>
            <li>Final accuracy depends on estimator quality and manual placement precision.</li>
          </ul>
        </details>
      )}

      {showModeHints && useGlobalSetpoints && !autoGlobalOrigin && (
        <details className="mission-operator-notes mission-operator-notes--mode">
          <summary>
            <span><FaInfoCircle aria-hidden="true" /> Global Mode Operator Notes</span>
            <small>Manual global placement without auto-correction</small>
          </summary>
          <ul>
            <li>Uses <strong>global GPS coordinates</strong> with the global position estimator.</li>
            <li>Operators must place drones <strong>exactly</strong> according to the Blender export and Mission Config plot.</li>
            <li>Launch-point deviations directly affect show geometry and timing.</li>
            <li>Confirm GPS quality and launch spacing before dispatch.</li>
            <li>Use Mission Config to verify each assigned launch position visually.</li>
          </ul>
        </details>
      )}

      {/* Auto Global Origin Correction (only for DRONE_SHOW_FROM_CSV + GLOBAL mode) */}
      {showModeHints && useGlobalSetpoints && (
        <div className="auto-origin-section">
          <div className="origin-checkbox-container">
            <label className="origin-checkbox-label">
              <input
                type="checkbox"
                checked={autoGlobalOrigin}
                onChange={(e) => onAutoGlobalOriginChange(e.target.checked)}
                className="origin-checkbox"
              />
              <span className="checkbox-text">
                Auto Global Launch Corrector
              </span>
            </label>
          </div>

          {autoGlobalOrigin && (
            <div className={`origin-warning ${!isOriginSet ? 'origin-missing' : ''}`}>
              <div className="warning-icon" aria-hidden="true">
                {isOriginSet ? <FaCheckCircle /> : <FaExclamationTriangle />}
              </div>
              <div className="warning-content">
                {!isOriginSet ? (
                  <>
                    <strong>Origin Not Set</strong>
                    <p>
                      Origin must be configured before using auto correction mode. 
                      <Link to="/mission-config" className="origin-link">
                        Set origin in Mission Config →
                      </Link>
                    </p>
                  </>
                ) : (
                  <>
                    <strong>Auto Correction Active</strong>
                    
                    {/* Origin confirmation */}
                    <div className="origin-confirmation">
                      <div className="origin-info-row">
                        <span className="origin-label">Origin:</span>
                        <span className="origin-coords">{formatOrigin()}</span>
                      </div>
                    </div>
                    
                    {/* Deviation summary */}
                    {deviationData && (
                      <div className="deviation-summary-compact">
                        {deviationSummary && deviationSummary.online > 0 ? (
                          <>
                            {/* Placement Status - Most prominent */}
                            {placementStatus && (
                              <div
                                className="deviation-stat placement-status-header"
                                style={{
                                  borderLeft: `4px solid ${placementStatus.color}`,
                                  backgroundColor: placementStatus.surface,
                                }}
                              >
                                <span className="deviation-label">Placement Accuracy:</span>
                                <span className="deviation-value placement-status-value" style={{ color: placementStatus.color, fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-bold)' }}>
                                  {placementStatus.icon} {placementStatus.text}
                                </span>
                              </div>
                            )}
                            
                            {/* Metrics Section */}
                            <div className="deviation-metrics-section">
                              <div className="deviation-stat">
                                <span className="deviation-label">Average Deviation:</span>
                                <span className="deviation-value">{deviationSummary.average_deviation?.toFixed(2) || '0.00'}m</span>
                              </div>
                              <div className="deviation-stat">
                                <span className="deviation-label">Worst Deviation:</span>
                                <span className="deviation-value">
                                  {deviationSummary.worst_deviation?.toFixed(2) || '0.00'}m
                                  {worstDeviationDrones.length > 0 && (
                                    <span className="deviation-drones"> (Drone{worstDeviationDrones.length > 1 ? 's' : ''} {worstDeviationDrones.join(', ')})</span>
                                  )}
                                </span>
                              </div>
                              <div className="deviation-stat">
                                <span className="deviation-label">Drones Online:</span>
                                <span className="deviation-value">{deviationSummary.online} drone{deviationSummary.online !== 1 ? 's' : ''}</span>
                              </div>
                            </div>
                            
                            {/* Status Summary - Only show if there are issues */}
                            {(warningAnalysis.gpsWarnings > 0 || warningAnalysis.placementWarnings > 0 || deviationSummary.errors > 0) && (
                              <div className="deviation-issues-section">
                                <div className="deviation-section-title">Status Issues:</div>
                                
                                {/* GPS Warnings (if any) */}
                                {warningAnalysis.gpsWarnings > 0 && (
                                  <div className="deviation-stat gps-warning-stat" title={warningAnalysis.warningDetails.filter(w => w.type === 'gps').map(w => `Drone ${w.hw_id}: ${w.message}`).join('\n')}>
                                    <span className="deviation-label">GPS Quality:</span>
                                    <span className="deviation-value gps-warning-value">
                                      {warningAnalysis.gpsWarnings} warning{warningAnalysis.gpsWarnings !== 1 ? 's' : ''}
                                      <span className="warning-info-note"> (not affecting placement)</span>
                                    </span>
                                  </div>
                                )}
                                
                                {/* Placement Warnings (only if deviation is actually bad) */}
                                {warningAnalysis.placementWarnings > 0 && (
                                  <div className="deviation-stat placement-warning-stat" title={warningAnalysis.warningDetails.filter(w => w.type === 'placement').map(w => `Drone ${w.hw_id}: ${w.message} (${w.deviation.toFixed(2)}m)`).join('\n')}>
                                    <span className="deviation-label">Placement:</span>
                                    <span className="deviation-value placement-warning-value">
                                      {warningAnalysis.placementWarnings} drone{warningAnalysis.placementWarnings !== 1 ? 's' : ''} needs adjustment
                                    </span>
                                  </div>
                                )}
                                
                                {/* Errors */}
                                {deviationSummary.errors > 0 && (
                                  <div className="deviation-stat error-stat" title={Object.entries(deviations).filter(([_, d]) => d.status === 'error').map(([hw_id, d]) => `Drone ${hw_id}: ${d.message || 'Error'}`).join('\n')}>
                                    <span className="deviation-label">Critical:</span>
                                    <span className="deviation-value error-value">
                                      {deviationSummary.errors} error{deviationSummary.errors !== 1 ? 's' : ''} detected
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}
                            
                            {/* All Good Message */}
                            {warningAnalysis.gpsWarnings === 0 && warningAnalysis.placementWarnings === 0 && deviationSummary.errors === 0 && placementStatus?.status === 'excellent' && (
                              <div className="deviation-all-good">
                                <span className="all-good-icon" aria-hidden="true"><FaCheckCircle /></span>
                                <span className="all-good-text">All drones are properly positioned and ready for launch</span>
                              </div>
                            )}
                            
                            {/* Warning details expandable - Only show if there are warnings/errors */}
                            {warningAnalysis.warningDetails.length > 0 && (
                              <details className="warning-details">
                                <summary className="warning-details-summary">
                                  {warningAnalysis.warningDetails.length === 1 
                                    ? 'View warning details' 
                                    : `View ${warningAnalysis.warningDetails.length} warning details`}
                                </summary>
                                <div className="warning-details-content">
                                  {warningAnalysis.warningDetails.map((warning, idx) => (
                                    <div key={idx} className="warning-detail-item">
                                      <div className="warning-detail-header">
                                        <strong>Drone {warning.hw_id}</strong>
                                        <span className={`warning-type-badge ${warning.type}-badge`}>
                                          {warning.type === 'gps' ? 'GPS' : 'Placement'}
                                        </span>
                                      </div>
                                      <div className="warning-detail-message">{warning.message}</div>
                                      {warning.deviation !== undefined && (
                                        <div className="warning-deviation">Deviation: {warning.deviation.toFixed(2)}m</div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </details>
                            )}
                          </>
                        ) : (
                          <div className="deviation-stat">
                            <span className="deviation-label">Status:</span>
                            <span className="deviation-value">Waiting for drone telemetry...</span>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {renderOperatorNotes('Correction limits', [
                      <>Drones will <strong>automatically correct</strong> their positions after takeoff and initial climb.</>,
                      <>Approximate placement is acceptable within the expected tolerance envelope.</>,
                      <>Good GPS fix quality is required for accurate correction.</>,
                      <>Drones still need <strong>network connectivity</strong> to fetch the shared origin from GCS.</>,
                      <><strong>Safety:</strong> place drones so correction paths do not cross or create collision risk.</>,
                      <>Launch will abort if a drone is too far from the expected starting position.</>,
                    ])}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Enhanced Mission Readiness for Swarm Trajectory Mode */}
      {missionType === DRONE_MISSION_TYPES.SWARM_TRAJECTORY && (
        <MissionReadinessCard
          refreshTrigger={0}
          clusterStatus={swarmTrajectoryStatus}
          loading={swarmTrajectoryStatusLoading}
          error={swarmTrajectoryStatusError}
          onRefresh={refreshSwarmTrajectoryStatus}
        />
      )}

      {swarmTrajectoryHints && (
        renderSnapshot({
          title: 'Swarm Trajectory Readiness',
          facts: [
            {
              label: 'Ready clusters:',
              value: `${swarmTrajectorySummary.scopeReadyClusterCount}/${swarmTrajectorySummary.scopeClusterCount || 0}`,
            },
            {
              label: 'Processed drones:',
              value: `${swarmTrajectorySummary.scopeProcessedDroneCount}/${swarmTrajectorySummary.scopeTargetDroneCount || swarmTrajectorySummary.scopeProcessedDroneCount || 0}`,
            },
            {
              label: 'Launch scope:',
              value: swarmTrajectorySummary.scopeMode === 'selected'
                ? `${swarmTrajectorySummary.scopeTargetDroneCount} selected drone${swarmTrajectorySummary.scopeTargetDroneCount === 1 ? '' : 's'}`
                : 'All targeted drones',
            },
            {
              label: 'Active package:',
              value: swarmTrajectorySummary.session.exists
                ? swarmTrajectorySummary.session.session_id
                : 'Not processed yet',
            },
            ...(swarmTrajectorySummary.scopePackageStats?.available
              ? [
                {
                  label: 'Mission clock:',
                  value: formatSwarmTrajectoryMissionSeconds(swarmTrajectorySummary.scopePackageStats.missionClockS),
                },
                {
                  label: 'Route entry:',
                  value: formatSwarmTrajectoryMissionSeconds(swarmTrajectorySummary.scopePackageStats.routeEntryTimeS),
                },
                {
                  label: 'Route motion:',
                  value: formatSwarmTrajectoryMissionSeconds(swarmTrajectorySummary.scopePackageStats.routeMotionTimeS),
                },
                {
                  label: 'Altitude envelope:',
                  value: formatSwarmTrajectoryAltitudeEnvelope(swarmTrajectorySummary.scopePackageStats),
                },
              ]
              : []),
          ],
          blockers: missionBlockers,
          warnings: missionWarnings,
          reference: (
            <p>
              Confirm leader routes in{' '}
              <Link to="/trajectory-planning" className="origin-link">
                Trajectory Planning
              </Link>{' '}
              and the processed package in{' '}
              <Link to="/swarm-trajectory" className="origin-link">
                Swarm Trajectory
              </Link>{' '}
              before launch.
            </p>
          ),
          notes: renderOperatorNotes('Trajectory notes', [
            'Selected drones fly their own generated global path package after processing; this is not live Smart Swarm follow mode.',
            'Launch and home truth still matter for armability, climb verification, drift handling, and RTL/LAND recovery, but they do not redefine the authored route geometry.',
          ]),
        })
      )}

      {smartSwarmHints && (
        renderSnapshot({
          title: 'Smart Swarm Readiness',
          facts: [
            {
              label: 'Top leaders:',
              value: smartSwarmInfo?.leaders?.length
                ? smartSwarmInfo.leaders.join(', ')
                : 'Not published',
            },
            {
              label: 'Follower links:',
              value: Object.values(smartSwarmInfo?.follower_details || {}).reduce(
                (count, followers) => count + (Array.isArray(followers) ? followers.length : 0),
                0,
              ),
            },
          ],
          warnings: missionWarnings,
          reference: (
            <p>
              Confirm the live topology in{' '}
              <Link to="/swarm-design" className="origin-link">
                Swarm Design
              </Link>{' '}
              before launch.
            </p>
          ),
          notes: renderOperatorNotes('Swarm notes', [
            'This mission uses the live Smart Swarm formation topology, not pre-processed leader trajectories.',
            'Verify leader and follower roles, offsets, and frame selection in Swarm Design before launch.',
            'Use immediate overrides like Hold, RTL, or Land to recover drones individually while the rest of the swarm stays in mode.',
          ]),
        })
      )}

      {showModeHints && (
        renderSnapshot({
          title: 'Drone Show Readiness',
          facts: [
            {
              label: 'Imported Show:',
              value: showImported
                ? `${showInfo.drone_count} drones • ${showInfo.duration_minutes}m ${showInfo.duration_seconds}s`
                : 'Not available',
            },
            ...(showImported
              ? [{
                label: 'Max Altitude:',
                value: `${showInfo.max_altitude} m`,
              }]
              : []),
          ],
          blockers: droneShowBlockers,
          warnings: droneShowWarnings,
          reference: (
            <p>
              Confirm imported geometry in{' '}
              <Link to="/manage-drone-show" className="origin-link">
                Show Design
              </Link>{' '}
              and launch setup in{' '}
              <Link to="/mission-config" className="origin-link">
                Mission Config
              </Link>{' '}
              before launch.
            </p>
          ),
        })
      )}

      {customShowHints && (
        renderSnapshot({
          title: 'Custom CSV Readiness',
          facts: [
            {
              label: 'Execution Mode:',
              value: 'LOCAL launch-frame only',
            },
            {
              label: 'Active CSV:',
              value: customShowReady
                ? `${customShowInfo.filename} • ${customShowInfo.duration_sec}s • ${customShowInfo.row_count} samples`
                : 'Not available',
            },
            ...(customShowReady
              ? [{
                label: 'Max Altitude:',
                value: `${customShowInfo.max_altitude} m`,
              }]
              : []),
          ],
          blockers: missionBlockers,
          warnings: missionWarnings,
          reference: (
            <p>
              Confirm the authored path in{' '}
              <Link to="/custom-show" className="origin-link">
                Custom Show
              </Link>{' '}
              and launch spacing in{' '}
              <Link to="/mission-config" className="origin-link">
                Mission Config
              </Link>{' '}
              before launch.
            </p>
          ),
          notes: renderOperatorNotes('Custom CSV notes', [
            'Each drone runs the same CSV relative to its own launch point.',
            'Global origin correction and shared-origin placement checks do not apply in this mode.',
            'Use this for advanced or manual testing, not for the normal SkyBrush multi-drone show pipeline.',
            'The uploaded CSV must already follow the MDS custom trajectory protocol; no conversion is done here.',
          ]),
        })
      )}

      <div className="mission-schedule">
        <div className="mission-schedule__header">
          <div>
            <h3>Timing</h3>
            <p>Now, short countdown, or exact UTC.</p>
          </div>
          <div className="mission-schedule__clock">
            <span>Clock</span>
            <strong>{clockOffsetLabel ? `GCS aligned · ${clockOffsetLabel}` : 'GCS aligned'}</strong>
          </div>
        </div>

        <div className="mission-schedule__modes">
          <label className={`mission-schedule__mode ${scheduleMode === COMMAND_SCHEDULE_MODES.NOW ? 'active' : ''}`}>
            <input
              type="radio"
              checked={scheduleMode === COMMAND_SCHEDULE_MODES.NOW}
              onChange={() => onScheduleModeChange(COMMAND_SCHEDULE_MODES.NOW)}
            />
            <span>Now</span>
            <small>After review</small>
          </label>
          <label className={`mission-schedule__mode ${scheduleMode === COMMAND_SCHEDULE_MODES.DELAY ? 'active' : ''}`}>
            <input
              type="radio"
              checked={scheduleMode === COMMAND_SCHEDULE_MODES.DELAY}
              onChange={() => onScheduleModeChange(COMMAND_SCHEDULE_MODES.DELAY)}
            />
            <span>Delay</span>
            <small>Controlled countdown</small>
          </label>
          <label className={`mission-schedule__mode ${scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE ? 'active' : ''}`}>
            <input
              type="radio"
              checked={scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE}
              onChange={() => onScheduleModeChange(COMMAND_SCHEDULE_MODES.ABSOLUTE)}
            />
            <span>Exact Time</span>
            <small>Absolute UTC</small>
          </label>
        </div>

        {scheduleMode === COMMAND_SCHEDULE_MODES.DELAY && (
          <div className="time-delay-slider">
            <label htmlFor="time-delay">Countdown: {timeDelay}s</label>
            <div className="mission-schedule__presets">
              {delayPresets.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className={`mission-schedule__preset ${Number(timeDelay) === preset ? 'active' : ''}`}
                  onClick={() => onTimeDelayChange(preset)}
                >
                  +{preset}s
                </button>
              ))}
            </div>
            <input
              type="range"
              id="time-delay"
              min="0"
              max="120"
              value={timeDelay}
              onChange={(e) => onTimeDelayChange(e.target.value)}
            />
          </div>
        )}

        {scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE && (
          <div className="time-picker">
            <label htmlFor="time-picker">Exact execution time</label>
            <input
              type="datetime-local"
              id="time-picker"
              value={selectedDateTime}
              onChange={(e) => onTimePickerChange(e.target.value)}
              step="1"
            />
          </div>
        )}

        <div className={`mission-schedule__summary ${schedulePreview.error ? 'error' : ''}`}>
          <strong>{schedulePreview.summary}</strong>
          <span>{schedulePreview.detail}</span>
          {schedulePreview.error && <small>{schedulePreview.error}</small>}
        </div>

        {scheduleDoctrine && (
          <div className="mission-schedule__policy">
            <strong>{scheduleDoctrine.label}</strong>
            <span>{scheduleDoctrine.detail}</span>
          </div>
        )}
      </div>

      <div className="mission-actions">
        <button onClick={onBack} className="back-button">
          Back
        </button>
        <button onClick={onSend} className="mission-button" disabled={!canSendMission}>
          Review & Send Command
        </button>
      </div>
    </div>
  );
};

export default MissionDetails;
