import React, { useEffect, useId } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import {
  FaCheckCircle,
  FaDrawPolygon,
  FaEdit,
  FaExclamationTriangle,
  FaMapMarkedAlt,
  FaMapMarkerAlt,
  FaMountain,
  FaPauseCircle,
  FaPlay,
  FaProjectDiagram,
  FaRedo,
  FaRoute,
  FaSatelliteDish,
  FaTimes,
  FaTrashAlt,
} from 'react-icons/fa';

import {
  ActionIconButton,
  OperatorCard,
  OperatorNotice,
  StatusBadge,
} from '../ui';
import {
  MISSION_GEOMETRY_TYPES,
  formatMetricArea,
  formatMetricDistance,
  summarizeMissionGeometry,
} from '../../utilities/missionGeometry';
import '../../styles/MissionPlanning.css';

const TOOL_DEFINITIONS = [
  { id: 'point', label: 'Point', icon: <FaMapMarkerAlt />, type: MISSION_GEOMETRY_TYPES.POINT },
  { id: 'waypoints', label: 'Waypoints', icon: <FaRoute />, type: MISSION_GEOMETRY_TYPES.WAYPOINT_SEQUENCE },
  { id: 'polyline', label: 'Path', icon: <FaProjectDiagram />, type: MISSION_GEOMETRY_TYPES.POLYLINE },
  { id: 'polygon', label: 'Area', icon: <FaDrawPolygon />, type: MISSION_GEOMETRY_TYPES.POLYGON },
  { id: 'corridor', label: 'Corridor', icon: <FaMapMarkedAlt />, type: MISSION_GEOMETRY_TYPES.CORRIDOR },
];

const ALTITUDE_MODES = [
  { id: 'fixed_msl', label: 'MSL', detail: 'Fixed altitude', icon: <FaSatelliteDish /> },
  { id: 'agl', label: 'AGL', detail: 'Terrain based', icon: <FaMountain /> },
  { id: 'imported', label: 'Imported', detail: 'Route values', icon: <FaRoute /> },
];

const getToneForStatus = (status = '') => {
  if (['ready', 'valid', 'success', 'online'].includes(status)) return 'success';
  if (['warning', 'degraded', 'review'].includes(status)) return 'warning';
  if (['blocked', 'danger', 'error', 'offline'].includes(status)) return 'danger';
  if (['running', 'active', 'info'].includes(status)) return 'info';
  return 'neutral';
};

const getDroneId = (drone) => String(drone?.id ?? drone?.hw_id ?? drone?.hw_ID ?? drone?.pos_id ?? '');
const getDroneLabel = (drone) => drone?.label || drone?.name || `Drone ${getDroneId(drone)}`;

function ModalShell({
  open,
  title,
  children,
  footer,
  tone = 'neutral',
  onClose,
  closeLabel = 'Close dialog',
}) {
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose?.();
      }
    };

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return ReactDOM.createPortal(
    <div
      className="mission-dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose?.();
        }
      }}
    >
      <section
        className={`mission-dialog__panel mission-dialog__panel--${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="mission-dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="mission-dialog__close"
            onClick={onClose}
            aria-label={closeLabel}
          >
            <FaTimes aria-hidden="true" />
          </button>
        </header>
        <div className="mission-dialog__body">{children}</div>
        {footer ? <footer className="mission-dialog__footer">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}

ModalShell.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  children: PropTypes.node.isRequired,
  footer: PropTypes.node,
  tone: PropTypes.oneOf(['neutral', 'warning', 'danger']),
  onClose: PropTypes.func,
  closeLabel: PropTypes.string,
};

export function MissionMapWorkspace({
  title,
  subtitle = '',
  status = null,
  toolbar = null,
  sidebar = null,
  footer = null,
  providerControls = null,
  fallbackNotice = null,
  children,
}) {
  return (
    <section className="mission-map-workspace" aria-label={title}>
      <header className="mission-map-workspace__header">
        <div className="mission-map-workspace__title">
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        <div className="mission-map-workspace__status">{status}</div>
      </header>
      {fallbackNotice ? <div className="mission-map-workspace__fallback">{fallbackNotice}</div> : null}
      <div className="mission-map-workspace__body">
        <div className="mission-map-workspace__map">
          {providerControls ? <div className="mission-map-workspace__provider">{providerControls}</div> : null}
          {toolbar ? <div className="mission-map-workspace__toolbar">{toolbar}</div> : null}
          <div className="mission-map-workspace__canvas">{children}</div>
        </div>
        {sidebar ? <aside className="mission-map-workspace__sidebar">{sidebar}</aside> : null}
      </div>
      {footer ? <div className="mission-map-workspace__footer">{footer}</div> : null}
    </section>
  );
}

MissionMapWorkspace.propTypes = {
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  status: PropTypes.node,
  toolbar: PropTypes.node,
  sidebar: PropTypes.node,
  footer: PropTypes.node,
  providerControls: PropTypes.node,
  fallbackNotice: PropTypes.node,
  children: PropTypes.node.isRequired,
};

export function MissionGeometryToolbar({
  activeTool = '',
  disabledTools = [],
  onSelectTool,
  onEditGeometry = null,
  onClearGeometry = null,
}) {
  const disabledSet = new Set(disabledTools);
  return (
    <div className="mission-geometry-toolbar" role="toolbar" aria-label="Mission geometry tools">
      {TOOL_DEFINITIONS.map((tool) => (
        <ActionIconButton
          key={tool.id}
          icon={tool.icon}
          label={`Use ${tool.label.toLowerCase()} geometry`}
          size="sm"
          active={activeTool === tool.id || activeTool === tool.type}
          disabled={disabledSet.has(tool.id) || disabledSet.has(tool.type)}
          onClick={() => onSelectTool?.(tool.type)}
        >
          {tool.label}
        </ActionIconButton>
      ))}
      {onEditGeometry ? (
        <ActionIconButton icon={<FaEdit />} label="Edit geometry" size="sm" onClick={onEditGeometry}>
          Edit
        </ActionIconButton>
      ) : null}
      {onClearGeometry ? (
        <ActionIconButton icon={<FaTrashAlt />} label="Clear geometry" tone="danger" size="sm" onClick={onClearGeometry}>
          Clear
        </ActionIconButton>
      ) : null}
    </div>
  );
}

MissionGeometryToolbar.propTypes = {
  activeTool: PropTypes.string,
  disabledTools: PropTypes.arrayOf(PropTypes.string),
  onSelectTool: PropTypes.func.isRequired,
  onEditGeometry: PropTypes.func,
  onClearGeometry: PropTypes.func,
};

export function MissionGeometrySummary({
  geometry,
  title = 'Geometry',
}) {
  const summary = summarizeMissionGeometry(geometry);
  const tone = summary.valid ? (summary.warnings.length ? 'warning' : 'success') : 'danger';

  return (
    <OperatorCard compact className="mission-geometry-summary" tone={tone}>
      <div className="mission-geometry-summary__header">
        <strong>{title}</strong>
        <StatusBadge tone={tone}>{summary.valid ? 'Valid' : 'Blocked'}</StatusBadge>
      </div>
      <dl className="mission-geometry-summary__metrics">
        <div>
          <dt>Points</dt>
          <dd>{summary.pointCount}</dd>
        </div>
        <div>
          <dt>Distance</dt>
          <dd>{formatMetricDistance(summary.lengthM)}</dd>
        </div>
        <div>
          <dt>Area</dt>
          <dd>{formatMetricArea(summary.areaSqM)}</dd>
        </div>
        {summary.type === MISSION_GEOMETRY_TYPES.CORRIDOR ? (
          <div>
            <dt>Width</dt>
            <dd>{summary.corridorWidthM ? formatMetricDistance(summary.corridorWidthM) : 'Unset'}</dd>
          </div>
        ) : null}
      </dl>
      {summary.errors.length || summary.warnings.length ? (
        <ul className="mission-geometry-summary__issues">
          {[...summary.errors, ...summary.warnings].map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
    </OperatorCard>
  );
}

MissionGeometrySummary.propTypes = {
  geometry: PropTypes.shape({
    type: PropTypes.string,
    point: PropTypes.oneOfType([PropTypes.object, PropTypes.array]),
    points: PropTypes.array,
    corridorWidthM: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  }).isRequired,
  title: PropTypes.string,
};

export function MissionDroneSelector({
  drones = [],
  selectedIds = [],
  readinessById = {},
  onToggleDrone,
  disabled = false,
  title = 'Aircraft',
}) {
  const selectedSet = new Set((selectedIds || []).map(String));
  const readyCount = drones.filter((drone) => {
    const id = getDroneId(drone);
    const status = readinessById[id]?.status || drone?.status || 'unknown';
    return getToneForStatus(status) === 'success';
  }).length;

  return (
    <OperatorCard compact className="mission-drone-selector">
      <div className="mission-drone-selector__header">
        <strong>{title}</strong>
        <StatusBadge tone={selectedSet.size ? 'success' : 'neutral'}>{selectedSet.size} selected</StatusBadge>
      </div>
      <div className="mission-drone-selector__meta">
        <span>{drones.length} listed</span>
        <span>{readyCount} ready</span>
      </div>
      <div className="mission-drone-selector__list" role="list">
        {drones.map((drone) => {
          const id = getDroneId(drone);
          const readiness = readinessById[id] || {};
          const status = readiness.status || drone.status || 'unknown';
          const selected = selectedSet.has(id);
          return (
            <label key={id || getDroneLabel(drone)} className="mission-drone-selector__row">
              <input
                type="checkbox"
                checked={selected}
                disabled={disabled || readiness.blocked}
                onChange={() => onToggleDrone?.(id)}
              />
              <span className="mission-drone-selector__identity">
                <strong>{getDroneLabel(drone)}</strong>
                {readiness.detail ? <small>{readiness.detail}</small> : null}
              </span>
              <StatusBadge tone={getToneForStatus(status)}>{readiness.label || status}</StatusBadge>
            </label>
          );
        })}
      </div>
    </OperatorCard>
  );
}

MissionDroneSelector.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.object),
  selectedIds: PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number])),
  readinessById: PropTypes.object,
  onToggleDrone: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
  title: PropTypes.string,
};

export function MissionAltitudeControl({
  mode,
  valueM,
  onModeChange,
  onValueChange,
  terrainStatus = null,
  disabled = false,
}) {
  const terrainTone = getToneForStatus(terrainStatus?.status || 'neutral');

  return (
    <fieldset className="mission-altitude-control" disabled={disabled}>
      <legend>Altitude</legend>
      <div className="mission-altitude-control__modes">
        {ALTITUDE_MODES.map((option) => (
          <button
            key={option.id}
            type="button"
            className={[
              'mission-altitude-control__mode',
              mode === option.id ? 'is-selected' : '',
            ].filter(Boolean).join(' ')}
            aria-pressed={mode === option.id}
            onClick={() => onModeChange?.(option.id)}
          >
            <span aria-hidden="true">{option.icon}</span>
            <strong>{option.label}</strong>
            <small>{option.detail}</small>
          </button>
        ))}
      </div>
      <label className="mission-altitude-control__input">
        <span>{mode === 'agl' ? 'Target AGL' : 'Altitude MSL'}</span>
        <input
          type="number"
          min="1"
          step="1"
          value={valueM ?? ''}
          onChange={(event) => onValueChange?.(event.target.value)}
          disabled={mode === 'imported'}
        />
        <span>m</span>
      </label>
      {terrainStatus ? (
        <div className="mission-altitude-control__terrain">
          <StatusBadge tone={terrainTone}>{terrainStatus.label || terrainStatus.status}</StatusBadge>
          {terrainStatus.detail ? <span>{terrainStatus.detail}</span> : null}
        </div>
      ) : null}
    </fieldset>
  );
}

MissionAltitudeControl.propTypes = {
  mode: PropTypes.oneOf(['fixed_msl', 'agl', 'imported']).isRequired,
  valueM: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  onModeChange: PropTypes.func.isRequired,
  onValueChange: PropTypes.func.isRequired,
  terrainStatus: PropTypes.shape({
    status: PropTypes.string,
    label: PropTypes.string,
    detail: PropTypes.node,
  }),
  disabled: PropTypes.bool,
};

export function MissionJobProgressDialog({
  open,
  title = 'Planning mission',
  job = {},
  onCancel = null,
  onRetry = null,
  onClose,
}) {
  const status = job.status || 'running';
  const failed = ['failed', 'timeout', 'canceled'].includes(status);
  const complete = ['succeeded', 'completed'].includes(status);
  const progressValue = Math.max(0, Math.min(100, Number(job.progressPercent ?? job.progress ?? 0)));
  const tone = failed ? 'danger' : complete ? 'neutral' : 'warning';

  return (
    <ModalShell
      open={open}
      title={title}
      tone={tone}
      onClose={onClose}
      footer={(
        <>
          {onCancel && !failed && !complete ? (
            <button type="button" className="operator-button operator-button--ghost" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          {onRetry && failed ? (
            <button type="button" className="operator-button operator-button--primary" onClick={onRetry}>
              Retry
            </button>
          ) : null}
          <button type="button" className="operator-button operator-button--primary" onClick={onClose}>
            {complete ? 'Done' : 'Close'}
          </button>
        </>
      )}
    >
      <div className="mission-job-progress">
        <div className="mission-job-progress__status">
          <StatusBadge tone={getToneForStatus(status)}>{status}</StatusBadge>
          {job.phase ? <span>{job.phase}</span> : null}
        </div>
        <div className="mission-job-progress__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progressValue)}>
          <span style={{ width: `${progressValue}%` }} />
        </div>
        {job.message ? <p>{job.message}</p> : null}
        {job.error ? (
          <OperatorNotice tone="danger" title="Planning error">
            {job.error}
          </OperatorNotice>
        ) : null}
        {Array.isArray(job.warnings) && job.warnings.length ? (
          <ul className="mission-job-progress__warnings">
            {job.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        ) : null}
      </div>
    </ModalShell>
  );
}

MissionJobProgressDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string,
  job: PropTypes.shape({
    status: PropTypes.string,
    progress: PropTypes.number,
    progressPercent: PropTypes.number,
    phase: PropTypes.string,
    message: PropTypes.node,
    error: PropTypes.node,
    warnings: PropTypes.arrayOf(PropTypes.string),
  }),
  onCancel: PropTypes.func,
  onRetry: PropTypes.func,
  onClose: PropTypes.func.isRequired,
};

export function MissionReviewLaunchDialog({
  open,
  title = 'Review mission',
  confirmLabel = 'Launch',
  mission = {},
  blockers = [],
  warnings = [],
  onConfirm,
  onCancel,
  busy = false,
}) {
  const canConfirm = blockers.length === 0 && !busy;
  return (
    <ModalShell
      open={open}
      title={title}
      tone={blockers.length ? 'danger' : warnings.length ? 'warning' : 'neutral'}
      onClose={onCancel}
      footer={(
        <>
          <button type="button" className="operator-button operator-button--ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="operator-button operator-button--primary"
            onClick={onConfirm}
            disabled={!canConfirm}
          >
            {busy ? 'Working...' : confirmLabel}
          </button>
        </>
      )}
    >
      <div className="mission-review-dialog">
        <dl className="mission-review-dialog__summary">
          {Object.entries(mission).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value || 'Not set'}</dd>
            </div>
          ))}
        </dl>
        {blockers.length ? (
          <OperatorNotice tone="danger" title="Blocked">
            <ul>
              {blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
            </ul>
          </OperatorNotice>
        ) : null}
        {warnings.length ? (
          <OperatorNotice tone="warning" title="Review">
            <ul>
              {warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </OperatorNotice>
        ) : null}
      </div>
    </ModalShell>
  );
}

MissionReviewLaunchDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string,
  confirmLabel: PropTypes.string,
  mission: PropTypes.object,
  blockers: PropTypes.arrayOf(PropTypes.string),
  warnings: PropTypes.arrayOf(PropTypes.string),
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  busy: PropTypes.bool,
};

export function MissionPlanStatusBar({
  mode,
  dronesLabel,
  geometryStatus,
  altitudeLabel,
  readiness,
  actionLabel = '',
  onAction = null,
}) {
  return (
    <div className="mission-plan-status-bar" role="status" aria-label="Mission plan status">
      <StatusBadge tone="info">{mode}</StatusBadge>
      <StatusBadge tone={dronesLabel ? 'success' : 'neutral'}>{dronesLabel || 'No aircraft'}</StatusBadge>
      <StatusBadge tone={geometryStatus?.valid ? 'success' : 'danger'}>
        {geometryStatus?.label || (geometryStatus?.valid ? 'Geometry valid' : 'Geometry needed')}
      </StatusBadge>
      <StatusBadge tone="neutral">{altitudeLabel}</StatusBadge>
      <StatusBadge tone={getToneForStatus(readiness?.status)}>{readiness?.label || 'Readiness unknown'}</StatusBadge>
      {actionLabel && onAction ? (
        <button type="button" className="mission-plan-status-bar__action" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

MissionPlanStatusBar.propTypes = {
  mode: PropTypes.string.isRequired,
  dronesLabel: PropTypes.string,
  geometryStatus: PropTypes.shape({
    valid: PropTypes.bool,
    label: PropTypes.string,
  }),
  altitudeLabel: PropTypes.string.isRequired,
  readiness: PropTypes.shape({
    status: PropTypes.string,
    label: PropTypes.string,
  }),
  actionLabel: PropTypes.string,
  onAction: PropTypes.func,
};

export const missionPlanningIcons = {
  check: <FaCheckCircle />,
  warning: <FaExclamationTriangle />,
  running: <FaPlay />,
  paused: <FaPauseCircle />,
  retry: <FaRedo />,
};
