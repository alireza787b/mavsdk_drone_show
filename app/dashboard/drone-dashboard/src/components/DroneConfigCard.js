import React, { useState, useEffect, memo } from 'react';
import PropTypes from 'prop-types';
import DroneGitStatus from './DroneGitStatus';
import { toast } from 'react-toastify';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faEdit,
  faTrash,
  faSave,
  faTimes,
  faCircle,
  faExclamationTriangle,
  faTimesCircle,
  faExclamationCircle,
  faPlusCircle,
  faSignal,
  faCheckCircle,
  faExchangeAlt,
  faCodeBranch,
  faInfoCircle,
} from '@fortawesome/free-solid-svg-icons';
import {
  areGitRevisionsEquivalent,
  buildKnownPositionIds,
  formatCompactDroneIdentity,
  formatDroneLabel,
  formatShowSlotLabel,
  findDuplicatePositionAssignment,
  getHeartbeatTimestamp,
  isPositiveIntegerId,
  normalizeComparableId,
  normalizeRuntimeIp,
} from '../utilities/missionIdentityUtils';
import {
  buildMissionConfigFormState,
  coerceMissionCustomFieldValueForEditor,
  createMissionCustomFieldDraft,
  CUSTOM_FIELD_TYPES,
  CUSTOM_FIELD_TYPE_OPTIONS,
  formatMissionCustomFieldValue,
  getMissionConfigCustomFields,
  getPromotedMissionConfigField,
  humanizeMissionConfigFieldKey,
  normalizeMissionCustomFieldKey,
  serializeMissionConfigFormState,
  validateMissionCustomFields,
} from '../utilities/missionConfigFields';
import { buildMissionSlotStatusPresentation } from '../utilities/missionSlotStatus';
import '../styles/DroneConfigCard.css';

const SERIAL_PORT_OPTIONS = [
  { value: '', label: 'SITL / none' },
  { value: '/dev/ttyS0', label: '/dev/ttyS0 (Raspberry Pi 4)' },
  { value: '/dev/ttyAMA0', label: '/dev/ttyAMA0 (Raspberry Pi 5)' },
  { value: '/dev/ttyTHS1', label: '/dev/ttyTHS1 (Jetson)' },
];

const BAUDRATE_OPTIONS = [
  { value: '0', label: '0 (SITL / no serial)' },
  { value: '9600', label: '9600' },
  { value: '57600', label: '57600 (Standard)' },
  { value: '115200', label: '115200 (High Speed)' },
  { value: '921600', label: '921600 (Very High Speed)' },
];

function getCustomFieldValuePreview(field) {
  if (!field) {
    return 'Not set';
  }

  return formatMissionCustomFieldValue(field.value, field.type);
}

/**
 * Read-only view of a drone card: Shows the drone's config data and status.
 */
const DroneReadOnlyView = memo(function DroneReadOnlyView({
  drone,
  gitStatus,
  gcsGitStatus,
  isNew,
  ipMismatch,
  heartbeatStatus,
  heartbeatAgeSec,
  heartbeatIP,
  networkInfo,
  onEdit,
  onRemove,
  onReplace,
  configPosId,
  assignedPosId,
  autoPosId,
  onAcceptConfigFromAuto,
  onAcceptConfigFromHb,
}) {
  const slotPresentation = buildMissionSlotStatusPresentation(configPosId, assignedPosId, autoPosId);
  const [activeInspector, setActiveInspector] = useState(slotPresentation.tone === 'review' ? 'slot' : null);

  /**
   * Returns the correct heartbeat status icon based on `heartbeatStatus`.
   */
  const getHeartbeatIcon = () => {
    switch (heartbeatStatus) {
      case 'Online (Recent)':
        return (
          <FontAwesomeIcon
            icon={faCircle}
            className="status-icon online"
            title="Online (Recent): Drone is actively sending heartbeat"
            aria-label="Online (Recent)"
          />
        );
      case 'Stale (>20s)':
        return (
          <FontAwesomeIcon
            icon={faExclamationTriangle}
            className="status-icon stale"
            title="Stale (>20s): Heartbeat hasn't been received recently"
            aria-label="Stale (>20s)"
          />
        );
      case 'Offline (>60s)':
        return (
          <FontAwesomeIcon
            icon={faTimesCircle}
            className="status-icon offline"
            title="Offline (>60s): Drone hasn't sent heartbeat in a long time"
            aria-label="Offline (>60s)"
          />
        );
      default:
        // "No heartbeat"
        return (
          <FontAwesomeIcon
            icon={faCircle}
            className="status-icon no-heartbeat"
            title="No Heartbeat: Drone is not connected or not sending heartbeat"
            aria-label="No Heartbeat"
          />
        );
    }
  };

  /**
   * Wi-Fi icon based on a numeric `strength`.
   */
  const getWifiIcon = (strength) => {
    if (strength >= 80) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon strong"
          title="Strong Wi-Fi Signal"
          aria-label="Strong Wi-Fi Signal"
        />
      );
    }
    if (strength >= 50) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon medium"
          title="Medium Wi-Fi Signal"
          aria-label="Medium Wi-Fi Signal"
        />
      );
    }
    if (strength > 0) {
      return (
        <FontAwesomeIcon
          icon={faSignal}
          className="wifi-icon weak"
          title="Weak Wi-Fi Signal"
          aria-label="Weak Wi-Fi Signal"
        />
      );
    }
    return (
      <FontAwesomeIcon
        icon={faSignal}
        className="wifi-icon none"
        title="No Wi-Fi Signal"
        aria-label="No Wi-Fi Signal"
      />
    );
  };

  const normalizedHwId = normalizeComparableId(drone.hw_id);
  const normalizedPosId = normalizeComparableId(drone.pos_id, normalizedHwId);
  const compactIdentity = formatCompactDroneIdentity(normalizedPosId, normalizedHwId, 'Unassigned');
  const isRoleSwap = normalizedHwId !== normalizedPosId;
  const serialPortLabel = drone.serial_port ? drone.serial_port : 'SITL / none';
  const baudrateLabel = drone.baudrate === '0' || drone.baudrate === 0 ? '0 (SITL / no serial)' : (drone.baudrate || '57600');
  const promotedField = getPromotedMissionConfigField(drone);
  const customFieldEntries = getMissionConfigCustomFields(drone);
  const secondaryCustomFieldEntries = promotedField
    ? customFieldEntries.filter((field) => field.key !== promotedField.key)
    : customFieldEntries;
  const visibleCustomFieldEntries = secondaryCustomFieldEntries.slice(0, 3);
  const hiddenCustomFieldCount = Math.max(secondaryCustomFieldEntries.length - visibleCustomFieldEntries.length, 0);
  const normalizedHeartbeatIp = normalizeRuntimeIp(heartbeatIP);
  const wifiSsid = typeof networkInfo?.wifi?.ssid === 'string' ? networkInfo.wifi.ssid.trim() : '';
  const ethernetInterface = typeof networkInfo?.ethernet?.interface === 'string'
    ? networkInfo.ethernet.interface.trim()
    : '';
  const wifiSignalStrength = Number(networkInfo?.wifi?.signal_strength_percent);
  const hasWifiSignal = Number.isFinite(wifiSignalStrength);
  const hasRuntimeConnectivity = Boolean(wifiSsid || ethernetInterface || hasWifiSignal);
  const isSitlProfile = !drone.serial_port && ['', '0'].includes(String(drone.baudrate ?? '0'));
  const showSimulatedNetworkFallback = isSitlProfile && !hasRuntimeConnectivity;
  const trajectorySourceLabel = normalizedPosId
    ? `Source Drone ${normalizedPosId}.csv`
    : 'Source file pending';
  const isGitInSync = typeof gitStatus?.in_sync_with_gcs === 'boolean'
    ? gitStatus.in_sync_with_gcs
    : Boolean(
        gcsGitStatus?.commit
        && gitStatus?.commit
        && areGitRevisionsEquivalent(gitStatus.commit, gcsGitStatus.commit)
      );
  const runtimePathLabel = normalizedHeartbeatIp || drone.ip || 'Pending';
  const runtimeLinkLabel = showSimulatedNetworkFallback
    ? 'SITL / simulated'
    : wifiSsid
      ? `Wi-Fi ${wifiSsid}`
      : ethernetInterface
        ? `Ethernet ${ethernetInterface}`
        : hasWifiSignal
          ? `Wi-Fi ${wifiSignalStrength}%`
          : 'Link telemetry unavailable';
  const gitCompactLabel = isGitInSync ? 'Synced' : gitStatus?.branch ? 'Review' : 'Unknown';
  const hasSecondaryDetails = Boolean(
    secondaryCustomFieldEntries.length
    || gitStatus
    || networkInfo
    || drone.ip
    || drone.mavlink_port
    || drone.serial_port
    || drone.baudrate
  );
  const slotIndicatorValue = slotPresentation.tone === 'verified'
    ? 'Aligned'
    : slotPresentation.tone === 'review'
      ? 'Review'
      : 'Pending';
  const slotIndicatorTone = slotPresentation.tone === 'verified'
    ? 'good'
    : slotPresentation.tone === 'review'
      ? 'review'
      : 'neutral';
  const slotIndicatorNote = slotPresentation.configStr
    ? `P${slotPresentation.configStr}`
    : 'No slot';
  const runtimeModeLabel = showSimulatedNetworkFallback ? 'SITL' : 'Hardware';
  const runtimeBadgeTone = showSimulatedNetworkFallback ? 'simulated' : 'hardware';
  const linkIndicatorValue = showSimulatedNetworkFallback
    ? 'Simulated'
    : wifiSsid
      ? 'Wi-Fi'
      : ethernetInterface
        ? 'Ethernet'
        : hasWifiSignal
          ? 'Wi-Fi'
          : 'Review';
  const linkIndicatorTone = showSimulatedNetworkFallback || wifiSsid || ethernetInterface || hasWifiSignal
    ? 'good'
    : 'review';
  const linkIndicatorNote = showSimulatedNetworkFallback
    ? runtimePathLabel
    : wifiSsid
      ? wifiSsid
      : ethernetInterface
        ? ethernetInterface
        : runtimePathLabel;
  const gitIndicatorNote = gitStatus?.branch
    ? `${gitStatus.branch} · ${gitStatus.commit ? gitStatus.commit.slice(0, 7) : 'n/a'}`
    : 'No git report';
  const inspectorButtons = [
    {
      key: 'slot',
      icon: slotPresentation.tone === 'verified' ? faCheckCircle : faExclamationTriangle,
      label: 'Slot',
      value: slotIndicatorValue,
      note: slotIndicatorNote,
      tone: slotIndicatorTone,
      title: `${slotPresentation.headline}. ${slotPresentation.detail}`,
    },
    {
      key: 'link',
      icon: faSignal,
      label: 'Link',
      value: linkIndicatorValue,
      note: linkIndicatorNote,
      tone: linkIndicatorTone,
      title: `Runtime connectivity. ${runtimeLinkLabel}.`,
    },
    {
      key: 'git',
      icon: faCodeBranch,
      label: 'Git',
      value: gitCompactLabel,
      note: gitIndicatorNote,
      tone: isGitInSync ? 'good' : 'review',
      title: isGitInSync ? 'Drone git revision matches GCS.' : 'Drone git revision differs from GCS or needs review.',
    },
    ...(secondaryCustomFieldEntries.length > 0
      ? [{
        key: 'fields',
        icon: faInfoCircle,
        label: 'Fields',
        value: `${secondaryCustomFieldEntries.length} saved`,
        note: secondaryCustomFieldEntries[0]?.label || 'Additional fields',
        tone: 'neutral',
        title: `${secondaryCustomFieldEntries.length} additional mission-config field${secondaryCustomFieldEntries.length === 1 ? '' : 's'} saved.`,
      }]
      : []),
  ];
  const toggleInspector = (key) => {
    setActiveInspector((current) => (current === key ? null : key));
  };

  const renderSlotInspectorPanel = () => (
    <div className={`position-status ${slotPresentation.tone}`}>
      <div className="position-summary">
        <div>
          <div className="position-headline">{slotPresentation.headline}</div>
          <p className="position-detail">{slotPresentation.detail}</p>
        </div>
        {slotPresentation.tone === 'verified' && (
          <FontAwesomeIcon
            icon={faCheckCircle}
            className="status-icon all-good"
            title="Mission slot sources are aligned"
          />
        )}
      </div>

      <div className="position-source-list">
        {slotPresentation.chips.map((chip) => (
          <div
            key={`${chip.label}-${chip.rawValue || 'missing'}`}
            className={`position-source-chip ${chip.tone}`}
            title={`${chip.label === 'Cfg' ? 'Configured slot' : chip.label === 'HB' ? 'Heartbeat slot' : 'Auto-detected slot'}: ${chip.value}`}
          >
            <span className="position-source-chip-label">{chip.label}</span>
            <span className="position-source-chip-value">{chip.value}</span>
          </div>
        ))}
      </div>

      <div className="slot-inspector-meta">
        <div className="slot-inspector-meta__row">
          <span className="slot-inspector-meta__label">Source file</span>
          <span className="slot-inspector-meta__value">{trajectorySourceLabel}</span>
        </div>
        <div className="slot-inspector-meta__row">
          <span className="slot-inspector-meta__label">Identity</span>
          <span className="slot-inspector-meta__value">{compactIdentity}</span>
        </div>
      </div>

      {(slotPresentation.actions.acceptAutoValue || slotPresentation.actions.acceptAssignedValue) && (
        <div className="accept-buttons">
          {slotPresentation.actions.acceptAutoValue && (
            <button
              type="button"
              className="accept-button"
              onClick={() => onAcceptConfigFromAuto?.(slotPresentation.actions.acceptAutoValue)}
              title="Accept auto-detected show slot"
              aria-label="Accept auto-detected show slot"
            >
              <FontAwesomeIcon icon={faCheckCircle} />
              Use Auto {`P${slotPresentation.actions.acceptAutoValue}`}
            </button>
          )}
          {slotPresentation.actions.acceptAssignedValue && (
            <button
              type="button"
              className="accept-button accept-assigned-btn"
              onClick={() => onAcceptConfigFromHb?.(slotPresentation.actions.acceptAssignedValue)}
              title="Accept heartbeat-assigned show slot"
              aria-label="Accept heartbeat-assigned show slot"
            >
              <FontAwesomeIcon icon={faCheckCircle} />
              Use HB {`P${slotPresentation.actions.acceptAssignedValue}`}
            </button>
          )}
        </div>
      )}

      {slotPresentation.footnote && (
        <small className="position-footnote">{slotPresentation.footnote}</small>
      )}
    </div>
  );

  const renderLinkInspectorPanel = () => (
    <div className="drone-inspector-panel__stack">
      <div className="info-section">
        <div className="info-row">
          <span className="info-label">Runtime mode</span>
          <span className="info-value">{showSimulatedNetworkFallback ? 'SITL / simulated' : 'Hardware / live'}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Telemetry path</span>
          <span className={`info-value ${ipMismatch ? 'mismatch' : ''}`}>
            {runtimePathLabel}
            {ipMismatch && heartbeatIP && (
              <FontAwesomeIcon
                icon={faExclamationCircle}
                title={`IP mismatch: heartbeat path is ${heartbeatIP}`}
                aria-label={`IP mismatch: heartbeat path is ${heartbeatIP}`}
              />
            )}
          </span>
        </div>
        <div className="info-row">
          <span className="info-label">MAVLink port</span>
          <span className="info-value">{drone.mavlink_port}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Serial transport</span>
          <span className="info-value">{serialPortLabel} · {baudrateLabel}</span>
        </div>
      </div>

      <div className="network-section">
        <div className="network-header">
          <FontAwesomeIcon icon={faSignal} />
          Runtime Connectivity
        </div>
        <div className="network-content">
          {showSimulatedNetworkFallback ? (
            <>
              <div className="network-row">
                <span className="network-label">Runtime mode</span>
                <span className="network-value">
                  SITL / simulated
                  <span className="network-status simulated">Expected</span>
                </span>
              </div>
              <div className="network-row">
                <span className="network-label">Telemetry path</span>
                <span className="network-value">{normalizedHeartbeatIp || drone.ip || 'Mission-config runtime path'}</span>
              </div>
              <div className="network-row">
                <span className="network-label">Physical links</span>
                <span className="network-value">Wi-Fi and Ethernet telemetry are not reported in SITL.</span>
              </div>
            </>
          ) : networkInfo ? (
            <>
              <div className="network-row">
                <span className="network-label">Wi-Fi network</span>
                <span className="network-value">
                  {networkInfo?.wifi?.ssid || 'N/A'}
                  <span className={`network-status ${networkInfo?.wifi?.ssid ? 'connected' : 'disconnected'}`}>
                    {networkInfo?.wifi?.ssid ? 'Connected' : 'Disconnected'}
                  </span>
                </span>
              </div>
              <div className="network-row">
                <span className="network-label">Signal</span>
                <span className="network-value">
                  {networkInfo?.wifi?.signal_strength_percent ?? 'N/A'}%
                  {getWifiIcon(networkInfo?.wifi?.signal_strength_percent)}
                </span>
              </div>
              <div className="network-row">
                <span className="network-label">Ethernet</span>
                <span className="network-value">
                  {networkInfo?.ethernet?.interface || 'N/A'}
                  <span className={`network-status ${networkInfo?.ethernet?.interface ? 'connected' : 'unknown'}`}>
                    {networkInfo?.ethernet?.interface ? 'Active' : 'Unknown'}
                  </span>
                </span>
              </div>
            </>
          ) : (
            <div className="network-row">
              <span className="network-label">Status</span>
              <span className="network-value">
                Runtime network telemetry unavailable
                <span className="network-status unknown">Unknown</span>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  const renderFieldsInspectorPanel = () => (
    <div className="custom-field-section">
      <div className="custom-field-section-header">
        <span className="custom-field-section-title">Additional Fields</span>
        <span className="custom-field-section-count">
          {secondaryCustomFieldEntries.length} saved
        </span>
      </div>
      <div className="custom-field-list">
        {visibleCustomFieldEntries.map((field) => (
          <div key={field.key} className="custom-field-row">
            <span className="custom-field-label">
              {field.label}
              {field.isPromoted && <span className="custom-field-badge">Promoted</span>}
            </span>
            <span className="custom-field-value">{getCustomFieldValuePreview(field)}</span>
          </div>
        ))}
        {hiddenCustomFieldCount > 0 && (
          <div className="custom-field-overflow">
            +{hiddenCustomFieldCount} more field{hiddenCustomFieldCount === 1 ? '' : 's'} available in edit mode
          </div>
        )}
      </div>
    </div>
  );

  const renderActiveInspectorPanel = () => {
    if (activeInspector === 'slot') {
      return renderSlotInspectorPanel();
    }

    if (activeInspector === 'link') {
      return renderLinkInspectorPanel();
    }

    if (activeInspector === 'git') {
      return (
        <DroneGitStatus
          gitStatus={gitStatus}
          gcsGitStatus={gcsGitStatus}
          droneName={`Drone ${drone.hw_id}`}
        />
      );
    }

    if (activeInspector === 'fields' && secondaryCustomFieldEntries.length > 0) {
      return renderFieldsInspectorPanel();
    }

    return null;
  };

  return (
    <>
      {isNew && (
        <div className="new-drone-badge" aria-label="Draft Assignment">
          <FontAwesomeIcon icon={faPlusCircle} /> Draft assignment
        </div>
      )}

      {/* Card Header */}
      <div className="drone-card-header">
        <div className="drone-id-section">
          <div className="identity-kicker">{formatDroneLabel(normalizedHwId)}</div>
          <div className="drone-title-row">
            <h3 className="drone-title">{compactIdentity}</h3>
          </div>
          <div className="identity-meta-row">
            <span
              className={`assignment-badge ${isRoleSwap ? 'role-swap' : 'default'}`}
              title={isRoleSwap ? 'Hardware ID and assigned show slot differ.' : 'Hardware ID and assigned show slot match.'}
            >
              {isRoleSwap ? 'Slot swap' : 'Own slot'}
            </span>
            <span className={`identity-runtime-chip ${runtimeBadgeTone}`}>
              {runtimeModeLabel}
            </span>
            {promotedField && (
              <div className="promoted-field-chip">
                <span className="promoted-field-label">{promotedField.label}</span>
                <span className="promoted-field-value">{getCustomFieldValuePreview(promotedField)}</span>
              </div>
            )}
          </div>
        </div>
        <div className="card-actions">
          <div className={`status-badge ${heartbeatStatus.toLowerCase().replace(/[^a-z]/g, '')}`}>
            {getHeartbeatIcon()}
            <span className="status-text">{heartbeatStatus}</span>
            {heartbeatAgeSec !== null && <span className="status-time">({heartbeatAgeSec}s)</span>}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="drone-content">
        <div className="operator-indicator-grid" aria-label="Operator card indicators">
          {inspectorButtons.map((indicator) => (
            <button
              key={indicator.key}
              type="button"
              className={`operator-indicator operator-indicator--${indicator.tone}${activeInspector === indicator.key ? ' is-active' : ''}`}
              onClick={() => toggleInspector(indicator.key)}
              aria-expanded={activeInspector === indicator.key}
              title={indicator.title}
            >
              <span className="operator-indicator__topline">
                <FontAwesomeIcon icon={indicator.icon} className="operator-indicator__icon" />
                <span className="operator-indicator__label">{indicator.label}</span>
              </span>
              <span className="operator-indicator__value">{indicator.value}</span>
              <span className="operator-indicator__note">{indicator.note}</span>
            </button>
          ))}
        </div>
        {hasSecondaryDetails && activeInspector && (
          <div className="drone-card-details-rail">
            <div className="drone-card-details-rail__header">
              <strong>{inspectorButtons.find((indicator) => indicator.key === activeInspector)?.label || 'Details'}</strong>
              <span>Tap the same indicator again to collapse.</span>
            </div>
            <div className="drone-card-details-rail__content">
              {renderActiveInspectorPanel()}
            </div>
          </div>
        )}

      </div>

      {/* Edit / Remove / Replace action buttons */}
      <div className="button-group">
        <button
          className="action-button secondary"
          onClick={onEdit}
          title="Edit drone configuration"
          aria-label="Edit drone configuration"
        >
          <FontAwesomeIcon icon={faEdit} /> Edit
        </button>
        {(heartbeatStatus === 'Offline (>60s)' || heartbeatStatus === 'No heartbeat') && onReplace && (
          <button
            className="action-button replace"
            onClick={onReplace}
            title="Replace this drone with a spare"
            aria-label="Replace this drone"
          >
            <FontAwesomeIcon icon={faExchangeAlt} /> Replace
          </button>
        )}
        <button
          className="action-button danger"
          onClick={onRemove}
          title="Remove this drone"
          aria-label="Remove this drone"
        >
          <FontAwesomeIcon icon={faTrash} /> Remove
        </button>
      </div>
    </>
  );
});

/**
 * Edit form: Allows user to modify hardware ID, IP, pos_id, etc.
 */
const DroneEditForm = memo(function DroneEditForm({
  droneData,
  errors,
  customFieldErrors,
  ipMismatch,
  heartbeatIP,
  onFieldChange,
  onCustomFieldChange,
  onCustomFieldKeyCommit,
  onAddCustomField,
  onRemoveCustomField,
  onAcceptIp,
  onSave,
  onCancel,
  hwIdOptions,
  configData,
  assignedPosId,
  autoPosId,
  onAcceptPos,
  onAcceptPosAuto,
}) {
  const [showPosChangeDialog, setShowPosChangeDialog] = useState(false);
  const [originalPosId] = useState(
    normalizeComparableId(droneData.pos_id, normalizeComparableId(droneData.hw_id))
  );
  const [useCustomSerialPort, setUseCustomSerialPort] = useState(
    () => !SERIAL_PORT_OPTIONS.some((option) => option.value === (droneData.serial_port ?? ''))
  );
  const [useCustomBaudrate, setUseCustomBaudrate] = useState(
    () => !BAUDRATE_OPTIONS.some((option) => option.value === String(droneData.baudrate ?? ''))
  );

  const currentHwId = normalizeComparableId(droneData.hw_id);
  const currentPosId = normalizeComparableId(droneData.pos_id);
  const isRoleSwap = currentHwId && currentPosId && currentHwId !== currentPosId;
  const hwIdSuggestions = Array.from(
    new Set((hwIdOptions || []).map((value) => normalizeComparableId(value)).filter(Boolean))
  ).sort((left, right) => Number.parseInt(left, 10) - Number.parseInt(right, 10));
  const knownPositionIds = buildKnownPositionIds(configData, [droneData.pos_id, assignedPosId, autoPosId]);
  const duplicatePositionDrone = findDuplicatePositionAssignment(configData, currentHwId, currentPosId);
  const hwIdInputId = `hw-id-input-${currentHwId || 'draft'}`;
  const hwIdSuggestionListId = `hw-id-suggestions-${currentHwId || 'draft'}`;
  const posIdInputId = `pos-id-input-${currentHwId || 'draft'}`;
  const posIdSuggestionListId = `pos-id-suggestions-${currentHwId || 'draft'}`;
  const serialPortValue = useCustomSerialPort
    ? 'CUSTOM'
    : (droneData.serial_port || '');
  const baudrateValue = useCustomBaudrate
    ? 'CUSTOM'
    : String(droneData.baudrate || '');
  const customFields = Array.isArray(droneData.custom_fields) ? droneData.custom_fields : [];

  /** Generic onChange for other fields. */
  const handleGenericChange = (e) => {
    onFieldChange(e);
  };

  const handleIdentityChange = (name) => (event) => {
    onFieldChange({
      target: {
        name,
        value: normalizeComparableId(event.target.value),
      },
    });
  };

  const handleIdentityQuickPick = (name, value) => {
    onFieldChange({
      target: {
        name,
        value: normalizeComparableId(value),
      },
    });
  };

  const handleSerialPortChange = (event) => {
    const { value } = event.target;
    if (value === 'CUSTOM') {
      setUseCustomSerialPort(true);
      if (SERIAL_PORT_OPTIONS.some((option) => option.value === (droneData.serial_port ?? ''))) {
        onFieldChange({
          target: {
            name: 'serial_port',
            value: '',
          },
        });
      }
      return;
    }

    setUseCustomSerialPort(false);
    onFieldChange({
      target: {
        name: 'serial_port',
        value,
      },
    });
  };

  const handleBaudrateChange = (event) => {
    const { value } = event.target;
    if (value === 'CUSTOM') {
      setUseCustomBaudrate(true);
      if (BAUDRATE_OPTIONS.some((option) => option.value === String(droneData.baudrate ?? ''))) {
        onFieldChange({
          target: {
            name: 'baudrate',
            value: '',
          },
        });
      }
      return;
    }

    setUseCustomBaudrate(false);
    onFieldChange({
      target: {
        name: 'baudrate',
        value,
      },
    });
  };

  const handleCustomFieldTypeChange = (fieldId, nextType) => {
    const field = customFields.find((entry) => entry.id === fieldId);
    const nextValue = coerceMissionCustomFieldValueForEditor(
      nextType,
      field ? field.value : ''
    );

    onCustomFieldChange(fieldId, {
      type: nextType,
      value: nextValue,
    });
  };

  const renderCustomFieldValueControl = (field) => {
    if (field.type === CUSTOM_FIELD_TYPES.BOOLEAN) {
      return (
        <select
          value={field.value === true ? 'true' : 'false'}
          onChange={(event) =>
            onCustomFieldChange(field.id, { value: event.target.value === 'true' })
          }
          className="form-select"
          aria-label={`${field.key || 'Custom field'} value`}
        >
          <option value="false">False</option>
          <option value="true">True</option>
        </select>
      );
    }

    if (field.type === CUSTOM_FIELD_TYPES.JSON) {
      return (
        <textarea
          value={field.value}
          onChange={(event) => onCustomFieldChange(field.id, { value: event.target.value })}
          className="form-textarea form-textarea-json"
          rows={4}
          spellCheck={false}
          placeholder='{"value": "example"}'
          aria-label={`${field.key || 'Custom field'} JSON value`}
        />
      );
    }

    return (
      <input
        type={field.type === CUSTOM_FIELD_TYPES.NUMBER ? 'number' : 'text'}
        value={field.value}
        onChange={(event) => onCustomFieldChange(field.id, { value: event.target.value })}
        className="form-input"
        inputMode={field.type === CUSTOM_FIELD_TYPES.NUMBER ? 'decimal' : undefined}
        placeholder={field.type === CUSTOM_FIELD_TYPES.NUMBER ? 'Enter numeric value' : 'Enter value'}
        aria-label={`${field.key || 'Custom field'} value`}
      />
    );
  };

  const handleSaveRequest = () => {
    if (currentPosId && originalPosId && currentPosId !== originalPosId) {
      setShowPosChangeDialog(true);
      return;
    }

    onSave();
  };

  const handleCancelPosChange = () => {
    setShowPosChangeDialog(false);
  };

  const handleConfirmPosChange = () => {
    setShowPosChangeDialog(false);
    onSave();
  };

  return (
    <>
      {showPosChangeDialog && (
        <div className="confirmation-dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true">
            <h4>Confirm Show Slot Change</h4>
            <p>
              You are changing the assigned show slot from <strong>{originalPosId}</strong> to{' '}
              <strong>{currentPosId}</strong>.
            </p>
            <p>
              This changes which trajectory file the drone will fly. Show slots are loaded from trajectory CSV files.
            </p>
            <p style={{ marginTop: '1rem' }}>Do you want to proceed?</p>
            <div className="dialog-buttons">
              <button className="confirm-button" onClick={handleConfirmPosChange}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelPosChange}>
                No
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="drone-edit-form">
        <div className="form-header">
          <div className="form-header-kicker">Edit Mission Assignment</div>
          <h3>{`${formatDroneLabel(currentHwId, 'New Drone')} · ${formatShowSlotLabel(currentPosId, 'Show Slot Unassigned')}`}</h3>
          <p className="form-header-copy">
            Hardware ID stays with the physical drone. Position ID selects the show slot and trajectory file. Smart Swarm follow-links still use Hardware ID.
          </p>
        </div>

        {/* Form Section */}
        <div className="form-section">
          <div className="form-section-block">
            <div className="form-section-title">Identity Assignment</div>
            <div className="form-section-description">
              Keep Hardware ID tied to the physical drone. Change Position ID only when this drone must fly a different slot.
            </div>
            <div className="form-grid">
              <div className="form-field">
                <label className="form-label" htmlFor={hwIdInputId}>
                  Hardware ID
                </label>
                <input
                  id={hwIdInputId}
                  type="text"
                  name="hw_id"
                  value={droneData.hw_id || ''}
                  onChange={handleIdentityChange('hw_id')}
                  className="form-input"
                  list={hwIdSuggestionListId}
                  inputMode="numeric"
                  placeholder="Enter physical drone ID"
                  aria-label="Hardware ID"
                />
                <datalist id={hwIdSuggestionListId}>
                  {hwIdSuggestions.map((id) => (
                    <option key={id} value={id}>{formatDroneLabel(id)}</option>
                  ))}
                </datalist>
                <div className="field-help">
                  The persistent identity printed on the drone and used by the runtime.
                </div>
                {hwIdSuggestions.length > 0 && (
                  <div className="suggestion-chip-group">
                    {hwIdSuggestions.slice(0, 8).map((id) => (
                      <button
                        key={id}
                        type="button"
                        className={`suggestion-chip ${currentHwId === id ? 'active' : ''}`}
                        onClick={() => handleIdentityQuickPick('hw_id', id)}
                      >
                        {formatDroneLabel(id)}
                      </button>
                    ))}
                  </div>
                )}
                {errors.hw_id && <span className="error-message">{errors.hw_id}</span>}
              </div>

              <div className="form-field">
                <label className="form-label" htmlFor={posIdInputId}>
                  Position ID
                </label>
                <input
                  id={posIdInputId}
                  type="text"
                  name="pos_id"
                  value={droneData.pos_id || ''}
                  onChange={handleIdentityChange('pos_id')}
                  className="form-input"
                  list={posIdSuggestionListId}
                  inputMode="numeric"
                  placeholder="Enter show slot / trajectory slot"
                  aria-label="Position ID"
                />
                <datalist id={posIdSuggestionListId}>
                  {knownPositionIds.map((id) => (
                    <option key={id} value={id}>{`Show Slot ${id}`}</option>
                  ))}
                </datalist>
                <div className="field-help">
                  The show slot this drone will fly. This selects the matching <code>Drone {'{pos_id}'}.csv</code> file.
                </div>
                {knownPositionIds.length > 0 && (
                  <div className="suggestion-chip-group">
                    {knownPositionIds.slice(0, 12).map((id) => (
                      <button
                        key={id}
                        type="button"
                        className={`suggestion-chip ${currentPosId === id ? 'active' : ''}`}
                        onClick={() => handleIdentityQuickPick('pos_id', id)}
                      >
                        {`Slot ${id}`}
                      </button>
                    ))}
                  </div>
                )}
                {errors.pos_id && <span className="error-message">{errors.pos_id}</span>}
                {duplicatePositionDrone && (
                  <div className="field-warning">
                    {`${formatShowSlotLabel(currentPosId)} is already assigned to ${formatDroneLabel(duplicatePositionDrone.hw_id)}.`}
                  </div>
                )}
              </div>
            </div>

            <div className={`assignment-status-callout ${!currentPosId ? 'attention' : isRoleSwap ? 'role-swap' : 'default'}`}>
              {!currentPosId
                ? 'Assign a show slot before saving this drone.'
                : isRoleSwap
                ? `Slot swap active: ${formatDroneLabel(currentHwId, 'Drone')} will fly ${formatShowSlotLabel(currentPosId, 'Show Slot')}.`
                : `${formatDroneLabel(currentHwId, 'Drone')} keeps ${formatShowSlotLabel(currentPosId, 'Show Slot')}.`}
            </div>
          </div>

          <div className="form-section-block">
            <div className="form-section-title">Network & Transport</div>
            <div className="form-grid">
              <div className="form-field">
                <label className="form-label">IP Address</label>
                <div className="input-with-icon">
                  <input
                    type="text"
                    name="ip"
                    value={droneData.ip || ''}
                    onChange={handleGenericChange}
                    className={`form-input ${ipMismatch ? 'input-invalid' : ''}`}
                    placeholder="Enter IP Address"
                    aria-label="IP Address"
                  />
                  {ipMismatch && (
                    <FontAwesomeIcon
                      icon={faExclamationCircle}
                      className="warning-icon"
                      title={`IP mismatch: Heartbeat IP=${heartbeatIP}`}
                      aria-label={`IP mismatch: Heartbeat IP=${heartbeatIP}`}
                    />
                  )}
                </div>
                {errors.ip && <span className="error-message">{errors.ip}</span>}
              </div>

              <div className="form-field">
                <label className="form-label">MAVLink Port</label>
                <input
                  type="text"
                  name="mavlink_port"
                  value={droneData.mavlink_port || ''}
                  onChange={handleGenericChange}
                  className="form-input"
                  placeholder="Enter MAVLink Port"
                  aria-label="MAVLink Port"
                />
                {errors.mavlink_port && (
                  <span className="error-message">{errors.mavlink_port}</span>
                )}
              </div>

              <div className="form-field">
                <label className="form-label">Serial Port</label>
                <select
                  name="serial_port"
                  value={serialPortValue}
                  onChange={handleSerialPortChange}
                  className="form-select"
                  aria-label="Serial Port"
                >
                  {SERIAL_PORT_OPTIONS.map((option) => (
                    <option key={option.value || 'blank'} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                  <option value="CUSTOM">Custom...</option>
                </select>
                {serialPortValue === 'CUSTOM' && (
                  <input
                    type="text"
                    name="serial_port"
                    value={droneData.serial_port || ''}
                    onChange={handleGenericChange}
                    className="form-input"
                    placeholder="e.g., /dev/ttyUSB0"
                    aria-label="Custom Serial Port"
                  />
                )}
              </div>

              <div className="form-field">
                <label className="form-label">Baudrate</label>
                <select
                  name="baudrate"
                  value={baudrateValue}
                  onChange={handleBaudrateChange}
                  className="form-select"
                  aria-label="Baudrate"
                >
                  {BAUDRATE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                  <option value="CUSTOM">Custom...</option>
                </select>
                {baudrateValue === 'CUSTOM' && (
                  <input
                    type="text"
                    name="baudrate"
                    value={droneData.baudrate || ''}
                    onChange={handleGenericChange}
                    className="form-input"
                    placeholder="e.g., 38400"
                    aria-label="Custom Baudrate"
                  />
                )}
                {errors.baudrate && <span className="error-message">{errors.baudrate}</span>}
              </div>
            </div>
          </div>

          <div className="form-section-block">
            <div className="form-section-header">
              <div>
                <div className="form-section-title">Additional Mission Fields</div>
                <div className="form-section-description">
                  Optional per-drone metadata such as callsign, notes, or maintenance tags. Saved in JSON and preserved across dashboard edits.
                </div>
              </div>
              <button
                type="button"
                className="action-button secondary compact"
                onClick={onAddCustomField}
                title="Add additional field"
                aria-label="Add additional field"
              >
                <FontAwesomeIcon icon={faPlusCircle} /> Add field
              </button>
            </div>

            {customFields.length > 0 ? (
              <div className="custom-field-editor-list">
                {customFields.map((field) => {
                  const fieldError = customFieldErrors?.[field.id] || {};
                  const normalizedPreviewKey = normalizeMissionCustomFieldKey(field.key);
                  return (
                    <div key={field.id} className="custom-field-editor-card">
                      <div className="custom-field-editor-grid">
                        <div className="form-field">
                          <label className="form-label">Field Name</label>
                          <input
                            type="text"
                            value={field.key}
                            onChange={(event) =>
                              onCustomFieldChange(field.id, { key: event.target.value })
                            }
                            onBlur={() => onCustomFieldKeyCommit(field.id)}
                            className={`form-input ${fieldError.key ? 'input-invalid' : ''}`}
                            placeholder="e.g., callsign"
                            spellCheck={false}
                            aria-label="Additional field name"
                          />
                          <div className="field-help">
                            Saved as lowercase snake_case.
                            {normalizedPreviewKey && normalizedPreviewKey !== field.key.trim() && (
                              <span className="field-help-preview">
                                {` Saved key: ${normalizedPreviewKey}`}
                              </span>
                            )}
                          </div>
                          {fieldError.key && <span className="error-message">{fieldError.key}</span>}
                        </div>

                        <div className="form-field custom-field-type">
                          <label className="form-label">Type</label>
                          <select
                            value={field.type}
                            onChange={(event) =>
                              handleCustomFieldTypeChange(field.id, event.target.value)
                            }
                            className="form-select"
                            aria-label="Additional field type"
                          >
                            {CUSTOM_FIELD_TYPE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="form-field custom-field-value-field">
                          <label className="form-label">
                            {humanizeMissionConfigFieldKey(field.key || 'value')}
                          </label>
                          {renderCustomFieldValueControl(field)}
                          {field.type === CUSTOM_FIELD_TYPES.JSON && (
                            <div className="field-help">
                              Use valid JSON for structured metadata. Keep operator-facing values as text when possible.
                            </div>
                          )}
                          {fieldError.value && <span className="error-message">{fieldError.value}</span>}
                        </div>

                        <button
                          type="button"
                          className="custom-field-remove-button"
                          onClick={() => onRemoveCustomField(field.id)}
                          title="Remove additional field"
                          aria-label={`Remove ${field.key || 'additional field'}`}
                        >
                          <FontAwesomeIcon icon={faTrash} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="custom-field-empty-state">
                No additional mission fields set for this drone.
              </div>
            )}
          </div>

          {ipMismatch && heartbeatIP && (
            <div className="mismatch-message">
              {`Heartbeat is reporting IP ${heartbeatIP}, which differs from the saved IP.`}
              <button
                type="button"
                className="action-button success"
                onClick={onAcceptIp}
                title="Accept heartbeat IP"
                aria-label="Accept heartbeat IP"
              >
                <FontAwesomeIcon icon={faCheckCircle} /> Accept
              </button>
            </div>
          )}

          {assignedPosId &&
            assignedPosId !== currentPosId &&
            assignedPosId !== '0' && (
              <div className="mismatch-message">
                {`Heartbeat reports Show Slot ${assignedPosId}, which differs from the current config.`}
                <button
                type="button"
                className="action-button success"
                onClick={onAcceptPos}
                title="Accept heartbeat-assigned show slot"
                aria-label="Accept heartbeat-assigned show slot"
                >
                  <FontAwesomeIcon icon={faCheckCircle} /> Accept
                </button>
              </div>
            )}

          {autoPosId && autoPosId !== '0' && autoPosId !== currentPosId && (
            <div className="mismatch-message">
              {`Auto-detection suggests Show Slot ${autoPosId}.`}
              <button
                type="button"
                className="action-button success"
                onClick={onAcceptPosAuto}
                title="Accept auto-detected show slot"
                aria-label="Accept auto-detected show slot"
              >
                <FontAwesomeIcon icon={faCheckCircle} /> Accept Auto
              </button>
            </div>
          )}
        </div>

        {/* Save / Cancel buttons */}
        <div className="button-group">
          <button
            className="action-button success"
            onClick={handleSaveRequest}
            title="Save changes"
            aria-label="Save changes"
          >
            <FontAwesomeIcon icon={faSave} /> Save
          </button>
          <button
            className="action-button secondary"
            onClick={onCancel}
            title="Cancel editing"
            aria-label="Cancel editing"
          >
            <FontAwesomeIcon icon={faTimes} /> Cancel
          </button>
        </div>

      </div>
    </>
  );
});

/**
 * Main DroneConfigCard component:
 * Decides between Read-Only or Edit mode, handles mismatch logic, etc.
 */
export default function DroneConfigCard({
  drone,
  gitStatus,
  gcsGitStatus,
  configData,
  availableHwIds,
  editingDroneId,
  setEditingDroneId,
  saveChanges,
  removeDrone,
  onReplace,
  networkInfo,
  heartbeatData = null, // might be null or undefined
}) {
  const isEditing = normalizeComparableId(editingDroneId) === normalizeComparableId(drone.hw_id);

  const getCompleteFormData = (droneObj) => {
    return buildMissionConfigFormState(droneObj);
  };

  // Local state for the edit form
  const [droneData, setDroneData] = useState(getCompleteFormData(drone));
  const [errors, setErrors] = useState({});

  // Ensure the dropdown includes current hw_id + available hw_ids
  const hwIdOptionsForEdit = React.useMemo(() => {
    const currentHwId = String(drone.hw_id);
    const options = [...(availableHwIds || [])];

    // Always include the current hw_id in options (so user can keep it)
    if (!options.includes(currentHwId)) {
      options.unshift(currentHwId);
    }

    return options.sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  }, [drone.hw_id, availableHwIds]);

  // Reset local form when toggling edit mode
  useEffect(() => {
    if (isEditing) {
      setDroneData(getCompleteFormData(drone));
      setErrors({});
    }
  }, [isEditing, drone]);

  // Safely handle heartbeat data
  const safeHb = heartbeatData || {};
  const heartbeatIp = normalizeRuntimeIp(safeHb.ip);
  const configuredIp = normalizeRuntimeIp(drone.ip);
  const timestampVal = getHeartbeatTimestamp(safeHb);
  const now = Date.now();
  const heartbeatAgeSec =
    timestampVal !== null
      ? Math.floor((now - timestampVal) / 1000)
      : null;

  // Determine textual heartbeat status
  let heartbeatStatus = 'No heartbeat';
  if (heartbeatAgeSec !== null) {
    if (heartbeatAgeSec < 20) heartbeatStatus = 'Online (Recent)';
    else if (heartbeatAgeSec < 60) heartbeatStatus = 'Stale (>20s)';
    else heartbeatStatus = 'Offline (>60s)';
  }

  // Mismatch checks for IP
  const ipMismatch = Boolean(heartbeatIp && configuredIp && heartbeatIp !== configuredIp);

  // Position IDs from config & heartbeat
  const configPosId = normalizeComparableId(drone.pos_id, drone.hw_id); // from config
  const assignedPosId = normalizeComparableId(safeHb.pos_id); // heartbeat assigned
  const autoPosId = normalizeComparableId(safeHb.detected_pos_id);

  // Additional highlight if mismatch or newly detected
  const hasAnyMismatch = ipMismatch || drone.isNew;

  // Status class for visual distinction
  const getStatusClass = () => {
    if (hasAnyMismatch) return ' mismatch-drone';
    if (heartbeatStatus === 'Online (Recent)') return ' status-online';
    if (heartbeatStatus === 'Stale (>20s)') return ' status-stale';
    if (heartbeatStatus === 'Offline (>60s)') return ' status-offline';
    return ' status-unknown';
  };

  const cardExtraClass = getStatusClass();

  /**
   * Validate local fields, then call `saveChanges` if no errors.
   */
  const handleLocalSave = () => {
    const validationErrors = {};
    const normalizedHwId = normalizeComparableId(droneData.hw_id);
    const normalizedPosId = normalizeComparableId(droneData.pos_id);
    const customFieldValidation = validateMissionCustomFields(droneData.custom_fields);

    if (!normalizedHwId) {
      validationErrors.hw_id = 'Hardware ID is required.';
    } else if (!isPositiveIntegerId(normalizedHwId)) {
      validationErrors.hw_id = 'Hardware ID must be a positive integer.';
    }
    if (!droneData.ip) {
      validationErrors.ip = 'IP Address is required.';
    }
    if (!droneData.mavlink_port) {
      validationErrors.mavlink_port = 'MAVLink Port is required.';
    } else if (!/^\d+$/.test(String(droneData.mavlink_port))) {
      validationErrors.mavlink_port = 'MAVLink Port must be a positive integer.';
    }
    // Note: x,y positions come from trajectory CSV files - not validated here
    if (!normalizedPosId) {
      validationErrors.pos_id = 'Position ID is required.';
    } else if (!isPositiveIntegerId(normalizedPosId)) {
      validationErrors.pos_id = 'Position ID must be a positive integer.';
    }
    if (droneData.baudrate !== '' && droneData.baudrate !== null && !/^\d+$/.test(String(droneData.baudrate))) {
      validationErrors.baudrate = 'Baudrate must be 0 or a positive integer.';
    }
    if (!customFieldValidation.isValid) {
      validationErrors.custom_fields = customFieldValidation.errorsById;
    }

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }

    const serializedDroneData = serializeMissionConfigFormState({
      ...droneData,
      hw_id: normalizedHwId,
      pos_id: normalizedPosId,
    });

    saveChanges(drone.hw_id, {
      ...serializedDroneData,
      isNew: false,
    });
  };

  return (
    <div className={`drone-config-card${cardExtraClass}`}>
      {isEditing ? (
        <DroneEditForm
          droneData={droneData}
          errors={errors}
          customFieldErrors={errors.custom_fields}
          ipMismatch={ipMismatch}
          heartbeatIP={heartbeatIp}
          assignedPosId={assignedPosId}
          autoPosId={autoPosId}
          onFieldChange={(e) => {
            const { name, value } = e.target;
            setDroneData((current) => ({ ...current, [name]: value }));
            setErrors((current) => ({ ...current, [name]: undefined }));
          }}
          onCustomFieldChange={(fieldId, patch) => {
            setDroneData((current) => ({
              ...current,
              custom_fields: (current.custom_fields || []).map((field) =>
                field.id === fieldId ? { ...field, ...patch } : field
              ),
            }));
            setErrors((current) => {
              if (!current.custom_fields?.[fieldId]) {
                return current;
              }
              const nextCustomFieldErrors = { ...current.custom_fields };
              delete nextCustomFieldErrors[fieldId];
              return { ...current, custom_fields: nextCustomFieldErrors };
            });
          }}
          onCustomFieldKeyCommit={(fieldId) => {
            setDroneData((current) => ({
              ...current,
              custom_fields: (current.custom_fields || []).map((field) =>
                field.id === fieldId
                  ? { ...field, key: normalizeMissionCustomFieldKey(field.key) }
                  : field
              ),
            }));
          }}
          onAddCustomField={() => {
            setDroneData((current) => ({
              ...current,
              custom_fields: [...(current.custom_fields || []), createMissionCustomFieldDraft()],
            }));
          }}
          onRemoveCustomField={(fieldId) => {
            setDroneData((current) => ({
              ...current,
              custom_fields: (current.custom_fields || []).filter((field) => field.id !== fieldId),
            }));
            setErrors((current) => {
              if (!current.custom_fields?.[fieldId]) {
                return current;
              }
              const nextCustomFieldErrors = { ...current.custom_fields };
              delete nextCustomFieldErrors[fieldId];
              return { ...current, custom_fields: nextCustomFieldErrors };
            });
          }}
          onAcceptIp={() => {
            if (heartbeatIp) {
              setDroneData((current) => ({ ...current, ip: heartbeatIp }));
            }
          }}
          onAcceptPos={() => {
            if (assignedPosId && assignedPosId !== '0') {
              setDroneData((current) => ({
                ...current,
                pos_id: assignedPosId,
              }));
            }
          }}
          onAcceptPosAuto={() => {
            if (autoPosId && autoPosId !== '0') {
              setDroneData((current) => ({
                ...current,
                pos_id: autoPosId,
              }));
            }
          }}
          onSave={handleLocalSave}
          onCancel={() => {
            setEditingDroneId(null);
            setDroneData(getCompleteFormData(drone));
            setErrors({});
          }}
          hwIdOptions={hwIdOptionsForEdit}
          configData={configData}
        />
      ) : (
        <DroneReadOnlyView
          drone={drone}
          gitStatus={gitStatus}
          gcsGitStatus={gcsGitStatus}
          isNew={drone.isNew}
          ipMismatch={ipMismatch}
          heartbeatStatus={heartbeatStatus}
          heartbeatAgeSec={heartbeatAgeSec}
          heartbeatIP={heartbeatIp}
          networkInfo={networkInfo}
          configPosId={configPosId}
          assignedPosId={assignedPosId}
          autoPosId={autoPosId}
          onEdit={() => setEditingDroneId(drone.hw_id)}
          onRemove={() => removeDrone(drone.hw_id)}
          onReplace={onReplace ? () => onReplace(drone.hw_id) : undefined}
          onAcceptConfigFromAuto={(detectedValue) => {
            if (!detectedValue || detectedValue === '0') return;
            // Note: x,y positions come from trajectory CSV - not stored in config
            saveChanges(drone.hw_id, {
              ...drone,
              pos_id: detectedValue
            });
            toast.success(`Accepted auto-detected show slot ${detectedValue}`);
          }}
          onAcceptConfigFromHb={(hbValue) => {
            if (!hbValue || hbValue === '0') return;
            // Note: x,y positions come from trajectory CSV - not stored in config
            saveChanges(drone.hw_id, {
              ...drone,
              pos_id: hbValue
            });
            toast.success(`Accepted heartbeat show slot ${hbValue}`);
          }}
        />
      )}
    </div>
  );
}

DroneConfigCard.propTypes = {
  /** The drone object from your config (or fetched data). */
  drone: PropTypes.object.isRequired,

  /** Git statuses if relevant to show in the UI. */
  gitStatus: PropTypes.object,
  gcsGitStatus: PropTypes.object,

  /** The entire configData array, to look up pos_id collisions. */
  configData: PropTypes.array.isRequired,
  availableHwIds: PropTypes.array.isRequired,

  /** If this card is currently in "editing" mode, it will show the edit form. */
  editingDroneId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  setEditingDroneId: PropTypes.func.isRequired,

  /** Callback to save the changes in parent state or server. */
  saveChanges: PropTypes.func.isRequired,

  /** Callback to remove the drone entirely. */
  removeDrone: PropTypes.func.isRequired,

  /** Optional: callback to open the Replace Drone wizard for this drone. */
  onReplace: PropTypes.func,

  /** Optional: network info object, if available. */
  networkInfo: PropTypes.object,

  /**
   * Optional: heartbeat data object, e.g. {
   *   ip, pos_id, detected_pos_id, timestamp, ...
   * }
   */
  heartbeatData: PropTypes.any,
};
