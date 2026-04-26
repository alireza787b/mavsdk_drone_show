import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import {
  FaBatteryHalf,
  FaClock,
  FaCompass,
  FaCrosshairs,
  FaHome,
  FaPlaneDeparture,
  FaSatellite,
} from 'react-icons/fa';
import { ConfirmDialog } from './ui';
import PrecisionMoveDialog from './PrecisionMoveDialog';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import { getMissionDisplayContext } from '../utilities/missionUtils';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';
import { buildActionCommand, sendDroneCommand } from '../services/droneApiService';
import { DRONE_ACTION_NAMES, DRONE_ACTION_TYPES } from '../constants/droneConstants';
import '../styles/TacticalDroneCard.css';

const GPS_FIX_LABELS = {
  0: 'No GPS',
  1: 'No fix',
  2: '2D',
  3: '3D',
  4: 'DGPS',
  5: 'RTK float',
  6: 'RTK fixed',
};

const formatNumber = (value, digits = 1, fallback = 'n/a') => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : fallback;
};

const formatMetricNumber = (value, digits = 1, fallback = 'n/a') => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }

  return Math.abs(numeric) >= 10 ? numeric.toFixed(0) : numeric.toFixed(digits);
};

const formatLastUpdate = (value) => {
  if (!value) {
    return 'n/a';
  }
  const timestamp = Number(value);
  const date = Number.isFinite(timestamp)
    ? new Date(timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000)
    : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const HEX_COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

const resolveMarkerColor = (candidate, fallback = getPlotThemeColors().primary) => {
  const normalized = String(candidate || '').trim();
  return HEX_COLOR_PATTERN.test(normalized) ? normalized : fallback;
};

const TacticalMetric = ({ icon: Icon, label, value, help }) => (
  <div
    className="tactical-drone-card__metric"
    aria-label={`${label}: ${typeof value === 'string' || typeof value === 'number' ? value : ''}`.trim()}
    data-help={help || label}
  >
    <Icon aria-hidden="true" />
    <span>{value}</span>
  </div>
);

TacticalMetric.propTypes = {
  icon: PropTypes.elementType.isRequired,
  label: PropTypes.string.isRequired,
  value: PropTypes.node.isRequired,
  help: PropTypes.string,
};

const TacticalDroneCard = ({ drone, onClose, className = '' }) => {
  const [pendingAction, setPendingAction] = useState(null);
  const [precisionMoveOpen, setPrecisionMoveOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const hwId = String(drone?.[FIELD_NAMES.HW_ID] ?? drone?.hw_id ?? '');
  const posId = drone?.[FIELD_NAMES.POS_ID] ?? drone?.pos_id;
  const identity = formatCompactDroneIdentity(posId, hwId, `H${hwId || '?'}`);
  const alias = String(drone?.operator_alias || drone?.callsign || '').trim();
  const displayTitle = alias || identity;
  const hardwareSubtitle = alias ? identity : '';
  const markerColor = resolveMarkerColor(drone?.marker_color);
  const missionDisplay = getMissionDisplayContext(drone?.mission, drone?.last_mission);
  const flightMode = getFlightModeTitle(drone?.flight_mode);
  const gpsFix = GPS_FIX_LABELS[Number(drone?.gps_fix_type)] || 'GPS n/a';
  const distanceToHome = Number.isFinite(Number(drone?.distance_to_home_m))
    ? `${formatNumber(drone.distance_to_home_m)} m`
    : 'Home n/a';
  const armed = drone?.is_armed === true ? 'Armed' : drone?.is_armed === false ? 'Disarmed' : 'Arm n/a';
  const lastSeen = formatLastUpdate(drone?.last_update);
  const followLabel = Number(drone?.follow_mode) === 0 ? 'Leader' : `H${drone.follow_mode}`;
  const isArmed = drone?.is_armed === true;
  const actionTargetLabel = displayTitle || identity;
  const actionTargetDescriptor = hardwareSubtitle || identity;

  const submitActionCommand = async (action) => {
    if (!hwId || !action) {
      setPendingAction(null);
      return;
    }

    const commandData = buildActionCommand(action.actionType, [hwId], 0);
    commandData.uiMeta = {
      operatorLabel: action.label,
      targetLabel: actionTargetLabel,
      targetDescriptor: actionTargetDescriptor,
    };

    try {
      setSubmitting(true);
      await sendDroneCommand(commandData);
      toast.success(`${action.label} sent to ${actionTargetLabel}.`);
    } catch (error) {
      console.error(`Failed to send ${action.label} from tactical card`, error);
      toast.error(`Failed to send ${action.label} to ${actionTargetLabel}.`);
    } finally {
      setSubmitting(false);
      setPendingAction(null);
    }
  };

  const submitPrecisionMove = async (commandData, options = {}) => {
    try {
      setSubmitting(true);
      const response = await sendDroneCommand({
        ...commandData,
        target_drones: [hwId],
        uiMeta: {
          ...(commandData.uiMeta || {}),
          targetLabel: actionTargetLabel,
          targetDescriptor: actionTargetDescriptor,
        },
      });
      const didSend = response?.success !== false;
      if (didSend) {
        toast.success(`${commandData?.uiMeta?.operatorLabel || 'Precision Move'} sent to ${actionTargetLabel}.`);
      }
      if (didSend && options.closeOnSuccess !== false) {
        setPrecisionMoveOpen(false);
      }
      return didSend;
    } catch (error) {
      console.error('Failed to submit tactical precision move', error);
      toast.error(`Failed to send Precision Move to ${actionTargetLabel}.`);
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  const quickActions = isArmed
    ? [
        {
          key: 'rtl',
          actionType: DRONE_ACTION_TYPES.RETURN_RTL,
          icon: FaHome,
          label: DRONE_ACTION_NAMES[DRONE_ACTION_TYPES.RETURN_RTL],
          help: 'Return this drone to launch',
          tone: 'warning',
        },
      ]
    : [
        {
          key: 'takeoff',
          actionType: DRONE_ACTION_TYPES.TAKE_OFF,
          icon: FaPlaneDeparture,
          label: DRONE_ACTION_NAMES[DRONE_ACTION_TYPES.TAKE_OFF],
          help: 'Take off using configured altitude',
        },
      ];

  return (
    <section
      className={`tactical-drone-card ${className}`.trim()}
      style={{ '--mds-tactical-drone-color': markerColor }}
      aria-label={`${displayTitle} tactical summary`}
    >
      <div className="tactical-drone-card__header">
        <div>
          <p className="tactical-drone-card__eyebrow">
            <span aria-label={`Last telemetry update ${lastSeen}`} data-help="Last telemetry update">
              <FaClock aria-hidden="true" />
              {lastSeen}
            </span>
          </p>
          <h3>{displayTitle}</h3>
          {hardwareSubtitle ? <span className="tactical-drone-card__subtitle">{hardwareSubtitle}</span> : null}
        </div>
        <span className="tactical-drone-card__state">{drone?.stateLabel || 'Unknown'}</span>
        {onClose && (
          <button
            type="button"
            className="tactical-drone-card__close"
            onClick={onClose}
            aria-label={`Close ${displayTitle} summary`}
          >
            ×
          </button>
        )}
      </div>

      <div className="tactical-drone-card__metrics" aria-label="Drone health summary">
        <TacticalMetric icon={FaCompass} label="Altitude" value={`${formatMetricNumber(drone?.altitude)} m`} />
        <TacticalMetric icon={FaHome} label="Distance home" value={Number.isFinite(Number(drone?.distance_to_home_m)) ? `${formatMetricNumber(drone.distance_to_home_m)} m` : distanceToHome} help="Horizontal distance to cached home position" />
        <TacticalMetric icon={FaBatteryHalf} label="Battery" value={drone?.battery_voltage ? `${formatNumber(drone.battery_voltage, 2)} V` : 'Batt n/a'} />
        <TacticalMetric icon={FaSatellite} label="GPS" value={`${gpsFix}${drone?.satellites_visible ? `/${drone.satellites_visible}` : ''}`} />
      </div>

      <div className="tactical-drone-card__badges" aria-label="Drone operational state">
        <span aria-label={`PX4 flight mode ${flightMode || 'not available'}`} data-help="PX4 flight mode">{flightMode || 'Mode n/a'}</span>
        <span aria-label={`Arm state ${armed}`} data-help="Arm state">{armed}</span>
        <span aria-label={`Current mission ${missionDisplay.currentMissionName || 'No mission'}`} data-help="Current mission">{missionDisplay.currentMissionName || 'No mission'}</span>
        <span aria-label={`Follow role ${followLabel}`} data-help="Follow role">{followLabel}</span>
      </div>

      <div className="tactical-drone-card__actions" aria-label={`${displayTitle} quick controls`}>
        {quickActions.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.key}
              type="button"
              className={`tactical-drone-card__action ${action.tone ? `tactical-drone-card__action--${action.tone}` : ''}`}
              onClick={() => setPendingAction(action)}
              disabled={submitting || !hwId}
              aria-label={`${action.label} ${displayTitle}`}
              title={action.help}
              data-help={action.help}
            >
              <Icon aria-hidden="true" />
            </button>
          );
        })}
        {isArmed && (
          <button
            type="button"
            className="tactical-drone-card__action"
            onClick={() => setPrecisionMoveOpen(true)}
            disabled={submitting || !hwId}
            aria-label={`Open precision jog for ${displayTitle}`}
            title="Open precision jog"
            data-help="Open precision jog"
          >
            <FaCrosshairs aria-hidden="true" />
          </button>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(pendingAction)}
        title="Confirm Drone Action"
        message={pendingAction ? `${pendingAction.help}. Confirm ${pendingAction.label} for ${actionTargetLabel}?` : ''}
        confirmLabel={pendingAction?.label || 'Confirm'}
        busy={submitting}
        onConfirm={() => submitActionCommand(pendingAction)}
        onCancel={() => setPendingAction(null)}
      />

      <PrecisionMoveDialog
        isOpen={precisionMoveOpen}
        targetLabel={actionTargetLabel}
        targetDescriptor={actionTargetDescriptor}
        targetCount={1}
        submitting={submitting}
        scopeLocked
        onClose={() => {
          if (!submitting) {
            setPrecisionMoveOpen(false);
          }
        }}
        onEditTargetScope={() => {}}
        onSubmit={submitPrecisionMove}
        onSubmitHold={submitPrecisionMove}
      />
    </section>
  );
};

TacticalDroneCard.propTypes = {
  drone: PropTypes.shape({
    hw_id: PropTypes.string,
    pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    operator_alias: PropTypes.string,
    callsign: PropTypes.string,
    position: PropTypes.arrayOf(PropTypes.number),
    geoPosition: PropTypes.arrayOf(PropTypes.number),
    stateLabel: PropTypes.string,
    follow_mode: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    altitude: PropTypes.number,
    marker_color: PropTypes.string,
    battery_voltage: PropTypes.number,
    flight_mode: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    is_armed: PropTypes.bool,
    gps_fix_type: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    satellites_visible: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    mission: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    last_mission: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    distance_to_home_m: PropTypes.number,
    speed_mps: PropTypes.number,
    last_update: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  }).isRequired,
  onClose: PropTypes.func,
  className: PropTypes.string,
};

export default TacticalDroneCard;
