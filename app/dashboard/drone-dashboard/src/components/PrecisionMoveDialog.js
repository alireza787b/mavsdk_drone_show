import React, { useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';

import { DRONE_ACTION_NAMES, DRONE_ACTION_TYPES } from '../constants/droneConstants';
import { getActionExecutionPolicy } from '../utilities/commandExecutionPolicy';
import '../styles/PrecisionMoveDialog.css';

const MOVE_STEP_OPTIONS = [0.25, 0.5, 1, 2, 5];
const YAW_STEP_OPTIONS = [15, 30, 45, 90];

const DEFAULT_FORM_STATE = Object.freeze({
  frame: 'body',
  axisPrimary: '0',
  axisSecondary: '0',
  axisVertical: '0',
  yawMode: 'hold_current',
  yawDegrees: '',
  speedMps: '',
  positionToleranceM: '',
  yawToleranceDeg: '',
  settleTimeSec: '',
  timeoutSec: '',
});

const FRAME_LABELS = {
  body: {
    primary: 'Forward (+) / Back (-)',
    secondary: 'Right (+) / Left (-)',
    vertical: 'Up (+) / Down (-)',
    translationKeys: ['forward', 'right', 'up'],
    description: 'Move relative to each drone’s current heading.',
  },
  ned: {
    primary: 'North (+) / South (-)',
    secondary: 'East (+) / West (-)',
    vertical: 'Up (+) / Down (-)',
    translationKeys: ['north', 'east', 'up'],
    description: 'Move in the shared local NED frame.',
  },
};

const YAW_MODE_OPTIONS = [
  { value: 'hold_current', label: 'Keep heading', hint: 'Do not rotate during the move.' },
  { value: 'relative_delta', label: 'Yaw delta', hint: 'Rotate from the current heading.' },
  { value: 'absolute_heading', label: 'Absolute heading', hint: 'Face an explicit heading in degrees.' },
];

function buildInitialState() {
  return { ...DEFAULT_FORM_STATE };
}

function parseSignedNumber(value) {
  if (value === '' || value === null || value === undefined) {
    return 0;
  }

  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : Number.NaN;
}

function parseOptionalPositiveNumber(value) {
  if (value === '' || value === null || value === undefined) {
    return null;
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return Number.NaN;
  }

  return numeric;
}

function formatSignedDistance(value, positiveLabel, negativeLabel) {
  if (Math.abs(value) <= 1e-9) {
    return `${positiveLabel}/${negativeLabel}: 0 m`;
  }

  const direction = value > 0 ? positiveLabel : negativeLabel;
  return `${direction} ${Math.abs(value)} m`;
}

function formatAxisValue(value) {
  if (Math.abs(value) <= 1e-9) {
    return '0';
  }
  return String(Number(value.toFixed(3)));
}

const PrecisionMoveDialog = ({
  isOpen,
  targetLabel,
  targetDescriptor,
  targetCount,
  submitting = false,
  onClose,
  onSubmit,
  onSubmitHold,
}) => {
  const [formState, setFormState] = useState(buildInitialState);
  const [quickMoveStepM, setQuickMoveStepM] = useState(1);
  const [quickYawStepDeg, setQuickYawStepDeg] = useState(30);

  useEffect(() => {
    if (isOpen) {
      setFormState(buildInitialState());
      setQuickMoveStepM(1);
      setQuickYawStepDeg(30);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !submitting) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, submitting]);

  const frameConfig = FRAME_LABELS[formState.frame] || FRAME_LABELS.body;

  const validation = useMemo(() => {
    const primary = parseSignedNumber(formState.axisPrimary);
    const secondary = parseSignedNumber(formState.axisSecondary);
    const vertical = parseSignedNumber(formState.axisVertical);
    const yawDegrees = formState.yawMode === 'hold_current'
      ? null
      : parseSignedNumber(formState.yawDegrees);
    const speedMps = parseOptionalPositiveNumber(formState.speedMps);
    const positionToleranceM = parseOptionalPositiveNumber(formState.positionToleranceM);
    const yawToleranceDeg = parseOptionalPositiveNumber(formState.yawToleranceDeg);
    const settleTimeSec = parseOptionalPositiveNumber(formState.settleTimeSec);
    const timeoutSec = parseOptionalPositiveNumber(formState.timeoutSec);

    const numericFields = [
      { label: frameConfig.primary, value: primary },
      { label: frameConfig.secondary, value: secondary },
      { label: frameConfig.vertical, value: vertical },
    ];
    const invalidAxis = numericFields.find(({ value }) => Number.isNaN(value));
    if (invalidAxis) {
      return { error: `${invalidAxis.label} must be numeric.`, payload: null };
    }

    if (formState.yawMode !== 'hold_current' && Number.isNaN(yawDegrees)) {
      return { error: 'Yaw degrees must be numeric.', payload: null };
    }

    if (Number.isNaN(speedMps)) {
      return { error: 'Approach speed must be greater than zero.', payload: null };
    }

    if (Number.isNaN(positionToleranceM)) {
      return { error: 'Position tolerance must be greater than zero.', payload: null };
    }

    if (Number.isNaN(yawToleranceDeg)) {
      return { error: 'Yaw tolerance must be greater than zero.', payload: null };
    }

    if (Number.isNaN(settleTimeSec)) {
      return { error: 'Settle time must be greater than zero.', payload: null };
    }

    if (Number.isNaN(timeoutSec)) {
      return { error: 'Timeout must be greater than zero.', payload: null };
    }

    const hasTranslation = [primary, secondary, vertical].some((value) => Math.abs(value) > 1e-9);
    const yawOnlyRelativeZero = formState.yawMode === 'relative_delta'
      && Math.abs(Number(yawDegrees || 0)) <= 1e-9
      && !hasTranslation;

    if (!hasTranslation && formState.yawMode === 'hold_current') {
      return { error: 'Enter a move vector or a yaw target before dispatching.', payload: null };
    }

    if (yawOnlyRelativeZero) {
      return { error: 'Relative yaw-only moves must use a non-zero yaw delta.', payload: null };
    }

    const [primaryKey, secondaryKey, verticalKey] = frameConfig.translationKeys;
    const translationPayload = {
      [primaryKey]: primary,
      [secondaryKey]: secondary,
      [verticalKey]: vertical,
    };

    const yawPayload = formState.yawMode === 'hold_current'
      ? { mode: 'hold_current' }
      : { mode: formState.yawMode, degrees: yawDegrees };

    const precisionMove = {
      frame: formState.frame,
      translation_m: translationPayload,
      yaw: yawPayload,
      hold_mode: 'px4_hold',
      ...(speedMps !== null ? { speed_m_s: speedMps } : {}),
      ...(positionToleranceM !== null ? { position_tolerance_m: positionToleranceM } : {}),
      ...(yawToleranceDeg !== null ? { yaw_tolerance_deg: yawToleranceDeg } : {}),
      ...(settleTimeSec !== null ? { settle_time_sec: settleTimeSec } : {}),
      ...(timeoutSec !== null ? { timeout_sec: timeoutSec } : {}),
    };

    return {
      error: null,
      payload: precisionMove,
      preview: {
        primary,
        secondary,
        vertical,
        yawMode: formState.yawMode,
        yawDegrees,
        speedMps,
      },
    };
  }, [formState, frameConfig]);

  const detailRows = useMemo(() => {
    if (!validation.preview) {
      return [];
    }

    const { primary, secondary, vertical, yawMode, yawDegrees, speedMps } = validation.preview;
    const movementSummary = [
      formatSignedDistance(primary, frameConfig.translationKeys[0], frameConfig.translationKeys[0] === 'forward' ? 'back' : 'south'),
      formatSignedDistance(secondary, frameConfig.translationKeys[1], frameConfig.translationKeys[1] === 'right' ? 'left' : 'west'),
      formatSignedDistance(vertical, 'up', 'down'),
    ];

    const yawSummary = yawMode === 'hold_current'
      ? 'Keep current heading'
      : yawMode === 'relative_delta'
        ? `Yaw delta ${Number(yawDegrees || 0)}°`
        : `Absolute heading ${Number(yawDegrees || 0)}°`;

    return [
      { label: 'Frame', value: frameConfig.description },
      { label: 'Translation', value: movementSummary.join(' · ') },
      { label: 'Yaw', value: yawSummary },
      { label: 'Speed', value: speedMps === null ? 'Use backend default' : `${speedMps} m/s` },
      { label: 'Execution policy', value: getActionExecutionPolicy({ actionKey: 'PRECISION_MOVE', isImmediate: true }) },
    ];
  }, [frameConfig.description, frameConfig.translationKeys, validation.preview]);

  const handleFieldChange = (field) => (event) => {
    setFormState((current) => ({
      ...current,
      [field]: event.target.value,
    }));
  };

  const adjustAxis = (field, delta) => {
    setFormState((current) => {
      const nextValue = parseSignedNumber(current[field]);
      const safeCurrentValue = Number.isNaN(nextValue) ? 0 : nextValue;
      return {
        ...current,
        [field]: formatAxisValue(safeCurrentValue + delta),
      };
    });
  };

  const adjustYawDelta = (delta) => {
    setFormState((current) => {
      const nextValue = parseSignedNumber(current.yawDegrees);
      const safeCurrentValue = Number.isNaN(nextValue) ? 0 : nextValue;
      return {
        ...current,
        yawMode: 'relative_delta',
        yawDegrees: formatAxisValue(safeCurrentValue + delta),
      };
    });
  };

  const resetQuickMove = () => {
    setFormState((current) => ({
      ...current,
      axisPrimary: '0',
      axisSecondary: '0',
      axisVertical: '0',
      yawMode: 'hold_current',
      yawDegrees: '',
    }));
  };

  const handleSubmit = async () => {
    if (!validation.payload) {
      return;
    }

    await onSubmit({
      missionType: String(DRONE_ACTION_TYPES.PRECISION_MOVE),
      triggerTime: '0',
      precision_move: validation.payload,
      uiMeta: {
        operatorLabel: DRONE_ACTION_NAMES[DRONE_ACTION_TYPES.PRECISION_MOVE],
        confirmationMessage: `Precision Move → ${targetLabel}. Dispatch now?`,
        triggerSummary: 'Immediate local offboard move on acceptance',
        details: detailRows,
      },
    });
  };

  const handleSubmitHold = async () => {
    await onSubmitHold({
      missionType: String(DRONE_ACTION_TYPES.HOLD),
      triggerTime: '0',
      uiMeta: {
        operatorLabel: DRONE_ACTION_NAMES[DRONE_ACTION_TYPES.HOLD],
        confirmationMessage: `Hold → ${targetLabel}. Dispatch now?`,
        triggerSummary: 'Immediate override on acceptance',
        details: [
          {
            label: 'Purpose',
            value: 'Interrupt current movement and hand the targeted drones to Hold immediately.',
          },
          {
            label: 'Execution policy',
            value: getActionExecutionPolicy({ actionKey: 'HOLD', isImmediate: true }),
          },
        ],
      },
    });
  };

  if (!isOpen) {
    return null;
  }

  return ReactDOM.createPortal(
    <div
      className="precision-move-dialog__overlay"
      onClick={() => {
        if (!submitting) {
          onClose();
        }
      }}
    >
      <div
        className="precision-move-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="precision-move-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="precision-move-dialog__header">
          <div>
            <p className="precision-move-dialog__eyebrow">Immediate flight action</p>
            <h3 id="precision-move-dialog-title">Precision Move</h3>
          </div>
          <button
            type="button"
            className="precision-move-dialog__close"
            onClick={onClose}
            disabled={submitting}
            aria-label="Close Precision Move dialog"
          >
            Close
          </button>
        </div>

        <div className="precision-move-dialog__scope">
          <span className="precision-move-dialog__scope-badge">{targetLabel}</span>
          <span className="precision-move-dialog__scope-badge">Immediate only</span>
          <span className="precision-move-dialog__scope-badge">Airborne + local position required</span>
        </div>

        <p className="precision-move-dialog__description">
          {targetDescriptor}. Each targeted drone resolves this move from its own current local state and then hands control back to PX4 Hold.
        </p>

        <section className="precision-move-dialog__section">
          <h4>Quick Move</h4>
          <p className="precision-move-dialog__hint">
            Use quick controls for common nudges, then fine-tune the exact values below if needed.
          </p>

          <div className="precision-move-dialog__quick-config">
            <div className="precision-move-dialog__step-group">
              <span>Move step</span>
              <div className="precision-move-dialog__chip-row" role="group" aria-label="Quick move step">
                {MOVE_STEP_OPTIONS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={quickMoveStepM === value ? 'is-active' : ''}
                    onClick={() => setQuickMoveStepM(value)}
                    disabled={submitting}
                  >
                    {value} m
                  </button>
                ))}
              </div>
            </div>

            <div className="precision-move-dialog__step-group">
              <span>Yaw step</span>
              <div className="precision-move-dialog__chip-row" role="group" aria-label="Quick yaw step">
                {YAW_STEP_OPTIONS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={quickYawStepDeg === value ? 'is-active' : ''}
                    onClick={() => setQuickYawStepDeg(value)}
                    disabled={submitting}
                  >
                    {value}°
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="precision-move-dialog__quick-grid">
            <button type="button" onClick={() => adjustAxis('axisPrimary', quickMoveStepM)} disabled={submitting}>
              + {frameConfig.translationKeys[0]}
            </button>
            <button type="button" onClick={() => adjustAxis('axisPrimary', -quickMoveStepM)} disabled={submitting}>
              - {frameConfig.translationKeys[0]}
            </button>
            <button type="button" onClick={() => adjustAxis('axisSecondary', quickMoveStepM)} disabled={submitting}>
              + {frameConfig.translationKeys[1]}
            </button>
            <button type="button" onClick={() => adjustAxis('axisSecondary', -quickMoveStepM)} disabled={submitting}>
              - {frameConfig.translationKeys[1]}
            </button>
            <button type="button" onClick={() => adjustAxis('axisVertical', quickMoveStepM)} disabled={submitting}>
              Up
            </button>
            <button type="button" onClick={() => adjustAxis('axisVertical', -quickMoveStepM)} disabled={submitting}>
              Down
            </button>
            <button type="button" onClick={() => adjustYawDelta(-quickYawStepDeg)} disabled={submitting}>
              Yaw left
            </button>
            <button type="button" onClick={() => adjustYawDelta(quickYawStepDeg)} disabled={submitting}>
              Yaw right
            </button>
          </div>

          <div className="precision-move-dialog__quick-actions">
            <button type="button" className="precision-move-dialog__ghost" onClick={resetQuickMove} disabled={submitting}>
              Reset quick values
            </button>
          </div>
        </section>

        <section className="precision-move-dialog__section">
          <h4>Reference Frame</h4>
          <div className="precision-move-dialog__toggle-group" role="group" aria-label="Reference frame">
            {Object.entries(FRAME_LABELS).map(([value, labels]) => (
              <button
                key={value}
                type="button"
                className={formState.frame === value ? 'is-active' : ''}
                onClick={() => setFormState((current) => ({ ...current, frame: value }))}
                disabled={submitting}
              >
                <strong>{value.toUpperCase()}</strong>
                <small>{labels.description}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="precision-move-dialog__section">
          <h4>Exact Values</h4>
          <p className="precision-move-dialog__hint">
            Signed metres: positive moves toward the first direction, negative reverses it. Manual edits stay in sync with the quick controls above.
          </p>
          <div className="precision-move-dialog__grid">
            <label>
              <span>{frameConfig.primary}</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                value={formState.axisPrimary}
                onChange={handleFieldChange('axisPrimary')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>{frameConfig.secondary}</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                value={formState.axisSecondary}
                onChange={handleFieldChange('axisSecondary')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>{frameConfig.vertical}</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                value={formState.axisVertical}
                onChange={handleFieldChange('axisVertical')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>Approach speed (m/s)</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                min="0.1"
                placeholder="Backend default"
                value={formState.speedMps}
                onChange={handleFieldChange('speedMps')}
                disabled={submitting}
              />
            </label>
          </div>
        </section>

        <section className="precision-move-dialog__section">
          <h4>Yaw</h4>
          <div className="precision-move-dialog__toggle-group precision-move-dialog__toggle-group--compact" role="group" aria-label="Yaw mode">
            {YAW_MODE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={formState.yawMode === option.value ? 'is-active' : ''}
                onClick={() => setFormState((current) => ({ ...current, yawMode: option.value }))}
                disabled={submitting}
              >
                <strong>{option.label}</strong>
                <small>{option.hint}</small>
              </button>
            ))}
          </div>
          {formState.yawMode !== 'hold_current' && (
            <label className="precision-move-dialog__single-field">
              <span>{formState.yawMode === 'relative_delta' ? 'Yaw delta (deg)' : 'Heading (deg)'}</span>
              <input
                type="number"
                inputMode="decimal"
                step="1"
                value={formState.yawDegrees}
                onChange={handleFieldChange('yawDegrees')}
                disabled={submitting}
              />
            </label>
          )}
        </section>

        <details className="precision-move-dialog__advanced">
          <summary>Advanced convergence controls</summary>
          <p className="precision-move-dialog__hint">
            Leave blank to use backend defaults for tolerance, settle time, and timeout.
          </p>
          <div className="precision-move-dialog__grid">
            <label>
              <span>Position tolerance (m)</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0.01"
                placeholder="Backend default"
                value={formState.positionToleranceM}
                onChange={handleFieldChange('positionToleranceM')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>Yaw tolerance (deg)</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.5"
                min="0.1"
                placeholder="Backend default"
                value={formState.yawToleranceDeg}
                onChange={handleFieldChange('yawToleranceDeg')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>Settle time (s)</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                min="0.1"
                placeholder="Backend default"
                value={formState.settleTimeSec}
                onChange={handleFieldChange('settleTimeSec')}
                disabled={submitting}
              />
            </label>
            <label>
              <span>Timeout (s)</span>
              <input
                type="number"
                inputMode="decimal"
                step="1"
                min="1"
                placeholder="Backend default"
                value={formState.timeoutSec}
                onChange={handleFieldChange('timeoutSec')}
                disabled={submitting}
              />
            </label>
          </div>
        </details>

        <section className="precision-move-dialog__review">
          <div className="precision-move-dialog__review-header">
            <h4>Dispatch Review</h4>
            <span>{targetCount} target drone{targetCount === 1 ? '' : 's'}</span>
          </div>
          {detailRows.map((detail) => (
            <p key={`${detail.label}-${detail.value}`}>
              <strong>{detail.label}:</strong> {detail.value}
            </p>
          ))}
          {validation.error && (
            <p className="precision-move-dialog__error" role="alert">
              {validation.error}
            </p>
          )}
        </section>

        <div className="precision-move-dialog__actions">
          <button type="button" className="precision-move-dialog__cancel" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            type="button"
            className="precision-move-dialog__hold"
            onClick={handleSubmitHold}
            disabled={submitting}
          >
            Dispatch Hold
          </button>
          <button
            type="button"
            className="precision-move-dialog__submit"
            onClick={handleSubmit}
            disabled={submitting || Boolean(validation.error)}
          >
            {submitting ? 'Dispatching…' : 'Dispatch Precision Move'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
};

PrecisionMoveDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  targetLabel: PropTypes.string.isRequired,
  targetDescriptor: PropTypes.string.isRequired,
  targetCount: PropTypes.number.isRequired,
  submitting: PropTypes.bool,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  onSubmitHold: PropTypes.func.isRequired,
};

export default PrecisionMoveDialog;
