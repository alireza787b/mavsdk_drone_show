import React, { useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import {
  FaArrowDown,
  FaArrowLeft,
  FaArrowRight,
  FaArrowUp,
  FaRedo,
  FaUndo,
} from 'react-icons/fa';

import { DRONE_ACTION_NAMES, DRONE_ACTION_TYPES } from '../constants/droneConstants';
import { getPrecisionMovePolicyResponse } from '../services/gcsApiService';
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
    label: 'Aircraft-relative',
    statusLabel: 'AIRCRAFT',
    primary: 'Forward (+) / Back (-)',
    secondary: 'Right (+) / Left (-)',
    vertical: 'Up (+) / Down (-)',
    translationKeys: ['forward', 'right', 'up'],
    description: 'Move relative to each drone’s current heading.',
  },
  ned: {
    label: 'Map-relative',
    statusLabel: 'MAP',
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

const CONTROL_MODE_OPTIONS = [
  {
    value: 'planned',
    label: 'Planned Move',
    hint: 'Build a staged move, then dispatch when ready.',
  },
  {
    value: 'live_jog',
    label: 'Live Jog',
    hint: 'Each control press sends one immediate step.',
  },
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

function formatRuntimeValue(value, unit, fallback = 'Runtime policy unavailable') {
  if (!Number.isFinite(Number(value))) {
    return fallback;
  }

  return `${Number(value)} ${unit}`.trim();
}

function buildPrecisionMoveResult(formState, frameConfig) {
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
}

const PrecisionMoveDialog = ({
  isOpen,
  targetLabel,
  targetDescriptor,
  targetCount,
  liveMonitor = null,
  submitting = false,
  onClose,
  onEditTargetScope,
  onSubmit,
  onSubmitHold,
}) => {
  const [formState, setFormState] = useState(buildInitialState);
  const [interactionMode, setInteractionMode] = useState('planned');
  const [quickMoveStepM, setQuickMoveStepM] = useState(1);
  const [quickYawStepDeg, setQuickYawStepDeg] = useState(30);
  const [showCustomMoveStep, setShowCustomMoveStep] = useState(false);
  const [showCustomYawStep, setShowCustomYawStep] = useState(false);
  const [policy, setPolicy] = useState(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState('');

  useEffect(() => {
    if (isOpen) {
      setFormState(buildInitialState());
      setInteractionMode('planned');
      setQuickMoveStepM(1);
      setQuickYawStepDeg(30);
      setShowCustomMoveStep(false);
      setShowCustomYawStep(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    let cancelled = false;
    setPolicyLoading(true);
    setPolicyError('');

    getPrecisionMovePolicyResponse()
      .then((response) => {
        if (cancelled) {
          return;
        }

        const payload = response?.data?.policy || response?.data || null;
        setPolicy(payload);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }

        console.error('Failed to load Precision Move policy:', error);
        setPolicy(null);
        setPolicyError('Runtime defaults unavailable. Dispatch still uses backend policy.');
      })
      .finally(() => {
        if (!cancelled) {
          setPolicyLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
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

  const validation = useMemo(
    () => buildPrecisionMoveResult(formState, frameConfig),
    [formState, frameConfig],
  );

  const buildDetailRows = (sourceState, preview, sourceFrameConfig = frameConfig) => {
    if (!preview) {
      return [];
    }

    const { primary, secondary, vertical, yawMode, yawDegrees, speedMps } = preview;
    const runtimeDefaults = policy?.defaults || {};
    const movementSummary = [
      formatSignedDistance(primary, sourceFrameConfig.translationKeys[0], sourceFrameConfig.translationKeys[0] === 'forward' ? 'back' : 'south'),
      formatSignedDistance(secondary, sourceFrameConfig.translationKeys[1], sourceFrameConfig.translationKeys[1] === 'right' ? 'left' : 'west'),
      formatSignedDistance(vertical, 'up', 'down'),
    ];

    const yawSummary = yawMode === 'hold_current'
      ? 'Keep current heading'
      : yawMode === 'relative_delta'
        ? `Yaw delta ${Number(yawDegrees || 0)}°`
        : `Absolute heading ${Number(yawDegrees || 0)}°`;

    const rows = [
      { label: 'Frame', value: sourceFrameConfig.label || sourceState.frame.toUpperCase() },
      { label: 'Translation', value: movementSummary.join(' · ') },
      { label: 'Yaw', value: yawSummary },
      {
        label: 'Speed',
        value: speedMps === null
          ? formatRuntimeValue(runtimeDefaults.speed_m_s, 'm/s')
          : `${speedMps} m/s`,
      },
    ];

    const tuningWasOverridden = [
      sourceState.positionToleranceM,
      sourceState.yawToleranceDeg,
      sourceState.settleTimeSec,
      sourceState.timeoutSec,
    ].some((value) => value !== '');

    if (tuningWasOverridden) {
      rows.push({
        label: 'Tuning',
        value: [
          sourceState.positionToleranceM === ''
            ? formatRuntimeValue(runtimeDefaults.position_tolerance_m, 'm')
            : `${Number(sourceState.positionToleranceM)} m`,
          sourceState.yawToleranceDeg === ''
            ? formatRuntimeValue(runtimeDefaults.yaw_tolerance_deg, 'deg')
            : `${Number(sourceState.yawToleranceDeg)}°`,
          sourceState.settleTimeSec === ''
            ? formatRuntimeValue(runtimeDefaults.settle_time_sec, 's')
            : `${Number(sourceState.settleTimeSec)} s`,
          sourceState.timeoutSec === ''
            ? formatRuntimeValue(runtimeDefaults.timeout_sec, 's')
            : `${Number(sourceState.timeoutSec)} s`,
        ].join(' · '),
      });
    }

    return rows;
  };

  const detailRows = useMemo(
    () => buildDetailRows(formState, validation.preview),
    [formState, policy?.defaults, validation.preview, frameConfig],
  );

  const runtimeDefaultsSummary = useMemo(() => {
    const defaults = policy?.defaults;
    const limits = policy?.limits;
    if (!defaults || !limits) {
      return null;
    }

    return [
      { label: 'Default speed', value: `${defaults.speed_m_s} m/s` },
      { label: 'Position tol', value: `${defaults.position_tolerance_m} m` },
      { label: 'Yaw tol', value: `${defaults.yaw_tolerance_deg}°` },
      { label: 'Settle', value: `${defaults.settle_time_sec} s` },
      { label: 'Timeout', value: `${defaults.timeout_sec} s` },
      { label: 'Max move', value: `${limits.max_translation_m} m` },
    ];
  }, [policy]);

  const liveMonitorSteps = useMemo(() => {
    if (!liveMonitor) {
      return null;
    }

    const accepted = Number(liveMonitor?.acks?.accepted ?? 0);
    const expected = Number(liveMonitor?.acks?.expected ?? 0);
    const active = Number(liveMonitor?.progress?.active ?? 0);
    const completed = Number(liveMonitor?.progress?.completed ?? 0);
    const stage = String(liveMonitor?.progress?.stage || '');
    let terminalLabel = 'Terminal';
    let terminalState = 'idle';
    if (stage === 'completed') {
      terminalLabel = 'Completed';
      terminalState = 'complete';
    } else if (stage === 'failed') {
      terminalLabel = 'Failed';
      terminalState = 'danger';
    } else if (stage === 'timeout') {
      terminalLabel = 'Timed out';
      terminalState = 'danger';
    } else if (stage === 'cancelled' || stage === 'superseded' || stage === 'partial') {
      terminalLabel = 'Interrupted';
      terminalState = 'warning';
    } else if (liveMonitor?.isTerminal) {
      terminalLabel = 'Terminal';
      terminalState = 'warning';
    }

    return [
      {
        key: 'accepted',
        label: 'Accepted',
        state: expected > 0 && accepted >= expected ? 'complete' : (accepted > 0 || stage !== 'awaiting_ack' ? 'active' : 'idle'),
      },
      {
        key: 'moving',
        label: 'Executing',
        state: active > 0 || stage === 'executing' || stage === 'finishing'
          ? 'active'
          : (completed > 0 || terminalState !== 'idle' ? 'complete' : 'idle'),
      },
      {
        key: 'hold',
        label: terminalLabel,
        state: terminalState,
      },
    ];
  }, [liveMonitor]);

  const stagedVectorSummary = useMemo(() => {
    const yawSummary = formState.yawMode === 'hold_current'
      ? 'yaw hold'
      : formState.yawMode === 'relative_delta'
        ? `yaw ${formState.yawDegrees || 0}°`
        : `hdg ${formState.yawDegrees || 0}°`;
    const frameLabel = frameConfig.statusLabel;

    return `${frameLabel} · ${formatAxisValue(parseSignedNumber(formState.axisPrimary))} / ${formatAxisValue(parseSignedNumber(formState.axisSecondary))} / ${formatAxisValue(parseSignedNumber(formState.axisVertical))} · ${yawSummary}`;
  }, [formState.axisPrimary, formState.axisSecondary, formState.axisVertical, formState.yawDegrees, formState.yawMode, frameConfig.statusLabel]);

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

  const dispatchPrecisionMove = async (payload, detailPayload, options = {}) => onSubmit({
    missionType: String(DRONE_ACTION_TYPES.PRECISION_MOVE),
    triggerTime: '0',
    precision_move: payload,
    uiMeta: {
      operatorLabel: DRONE_ACTION_NAMES[DRONE_ACTION_TYPES.PRECISION_MOVE],
      confirmationMessage: `Precision Move → ${targetLabel}. Dispatch now?`,
      triggerSummary: detailPayload?.triggerSummary || 'Immediate local offboard move on acceptance',
      details: detailPayload?.details || detailRows,
    },
  }, options);

  const buildQuickStepState = ({
    primary = 0,
    secondary = 0,
    vertical = 0,
    yawMode = 'hold_current',
    yawDegrees = '',
  }) => ({
    ...formState,
    axisPrimary: formatAxisValue(primary),
    axisSecondary: formatAxisValue(secondary),
    axisVertical: formatAxisValue(vertical),
    yawMode,
    yawDegrees: yawMode === 'hold_current' ? '' : formatAxisValue(yawDegrees),
  });

  const dispatchLiveJog = async (stepConfig) => {
    const quickState = buildQuickStepState(stepConfig);
    const quickValidation = buildPrecisionMoveResult(quickState, frameConfig);
    if (!quickValidation.payload) {
      return false;
    }

    const quickDetails = buildDetailRows(quickState, quickValidation.preview, frameConfig);
    return dispatchPrecisionMove(
      quickValidation.payload,
      {
        triggerSummary: 'Immediate single-step jog on acceptance',
        details: quickDetails,
      },
      { closeOnSuccess: false },
    );
  };

  const handleSubmit = async () => {
    if (!validation.payload) {
      return;
    }

    await dispatchPrecisionMove(validation.payload, {
      triggerSummary: 'Immediate local offboard move on acceptance',
      details: detailRows,
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
    }, { closeOnSuccess: false });
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

        <section className="precision-move-dialog__section precision-move-dialog__section--compact">
          <div className="precision-move-dialog__section-header">
            <h4>Scope</h4>
            <button
              type="button"
              className="precision-move-dialog__ghost"
              onClick={onEditTargetScope}
              disabled={submitting}
            >
              Edit scope
            </button>
          </div>
          <div className="precision-move-dialog__scope-summary">
            <button
              type="button"
              className="precision-move-dialog__scope-card precision-move-dialog__scope-card--interactive"
              onClick={onEditTargetScope}
              disabled={submitting}
            >
              <span>Targets</span>
              <strong>{targetLabel}</strong>
              <small>{targetDescriptor}</small>
            </button>
            <div className="precision-move-dialog__scope-card">
              <span>Execution</span>
              <strong>Immediate only</strong>
              <small>No queue or delay path.</small>
            </div>
            <div className="precision-move-dialog__scope-card">
              <span>Prereq</span>
              <strong>Airborne + local position</strong>
              <small>Each drone resolves from its own current state.</small>
            </div>
          </div>
        </section>

        {liveMonitor && liveMonitorSteps && (
          <section className="precision-move-dialog__section precision-move-dialog__section--compact">
            <div className="precision-move-dialog__section-header">
              <h4>Live Command Status</h4>
              <span className="precision-move-dialog__live-badge">{liveMonitor.progress?.label || 'Command update'}</span>
            </div>
            <div className="precision-move-dialog__status-strip" role="list" aria-label="Live command progress">
              {liveMonitorSteps.map((step) => (
                <div
                  key={step.key}
                  role="listitem"
                  className={`precision-move-dialog__status-step precision-move-dialog__status-step--${step.state}`}
                >
                  <span>{step.label}</span>
                </div>
              ))}
            </div>
            <div className="precision-move-dialog__status-meta">
              <strong>{liveMonitor.commandLabel}</strong>
              <span>{liveMonitor.progress?.message}</span>
              <span>
                Accepted {liveMonitor.acks?.accepted ?? 0}/{liveMonitor.acks?.expected ?? 0}
                {' · '}
                Active {liveMonitor.progress?.active ?? 0}
                {' · '}
                Completed {liveMonitor.progress?.completed ?? 0}
              </span>
            </div>
          </section>
        )}

        <section className="precision-move-dialog__section">
          <div className="precision-move-dialog__section-header">
            <h4>Control Surface</h4>
            <div className="precision-move-dialog__scope">
              <span className="precision-move-dialog__scope-badge">{frameConfig.label}</span>
              <span className="precision-move-dialog__scope-badge">
                {interactionMode === 'live_jog' ? 'Live jog armed' : 'Planned move'}
              </span>
            </div>
          </div>

          <div className="precision-move-dialog__subsection">
            <div className="precision-move-dialog__toggle-group" role="group" aria-label="Control mode">
              {CONTROL_MODE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={interactionMode === option.value ? 'is-active' : ''}
                  onClick={() => setInteractionMode(option.value)}
                  disabled={submitting}
                >
                  <strong>{option.label}</strong>
                  <small>{option.hint}</small>
                </button>
              ))}
            </div>

            <div className="precision-move-dialog__toggle-group" role="group" aria-label="Reference frame">
              {Object.entries(FRAME_LABELS).map(([value, labels]) => (
                <button
                  key={value}
                  type="button"
                  className={formState.frame === value ? 'is-active' : ''}
                  onClick={() => setFormState((current) => ({ ...current, frame: value }))}
                  disabled={submitting}
                >
                  <strong>{labels.label}</strong>
                  <small>{labels.description}</small>
                </button>
              ))}
            </div>
          </div>

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
              {showCustomMoveStep ? (
                <label className="precision-move-dialog__step-input">
                  <span>Custom</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0.05"
                    step="0.05"
                    value={quickMoveStepM}
                    onChange={(event) => {
                      const nextValue = Number(event.target.value);
                      if (Number.isFinite(nextValue) && nextValue > 0) {
                        setQuickMoveStepM(nextValue);
                      }
                    }}
                    disabled={submitting}
                  />
                </label>
              ) : (
                <button
                  type="button"
                  className="precision-move-dialog__ghost"
                  onClick={() => setShowCustomMoveStep(true)}
                  disabled={submitting}
                >
                  Custom step
                </button>
              )}
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
              {showCustomYawStep ? (
                <label className="precision-move-dialog__step-input">
                  <span>Custom</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="1"
                    step="1"
                    value={quickYawStepDeg}
                    onChange={(event) => {
                      const nextValue = Number(event.target.value);
                      if (Number.isFinite(nextValue) && nextValue > 0) {
                        setQuickYawStepDeg(nextValue);
                      }
                    }}
                    disabled={submitting}
                  />
                </label>
              ) : (
                <button
                  type="button"
                  className="precision-move-dialog__ghost"
                  onClick={() => setShowCustomYawStep(true)}
                  disabled={submitting}
                >
                  Custom yaw
                </button>
              )}
            </div>
          </div>

          <div className="precision-move-dialog__mode-strip" aria-label="Control mode summary">
            <span className="precision-move-dialog__live-badge">Step {quickMoveStepM} m</span>
            <span className="precision-move-dialog__live-badge">Yaw {quickYawStepDeg}°</span>
            <span className="precision-move-dialog__live-badge">
              {interactionMode === 'live_jog' ? 'Tap control to send now' : 'Pad edits the staged move'}
            </span>
          </div>

          <div className="precision-move-dialog__controller">
            <div className="precision-move-dialog__controller-pad">
              <button
                type="button"
                className="precision-move-dialog__control precision-move-dialog__control--forward"
                onClick={() => (
                  interactionMode === 'live_jog'
                    ? dispatchLiveJog({ primary: quickMoveStepM })
                    : adjustAxis('axisPrimary', quickMoveStepM)
                )}
                disabled={submitting}
              >
                <FaArrowUp aria-hidden="true" />
                <span>{frameConfig.translationKeys[0]}</span>
                <small>+{quickMoveStepM} m</small>
              </button>
              <button
                type="button"
                className="precision-move-dialog__control precision-move-dialog__control--left"
                onClick={() => (
                  interactionMode === 'live_jog'
                    ? dispatchLiveJog({ secondary: -quickMoveStepM })
                    : adjustAxis('axisSecondary', -quickMoveStepM)
                )}
                disabled={submitting}
              >
                <FaArrowLeft aria-hidden="true" />
                <span>{frameConfig.translationKeys[1] === 'right' ? 'left' : 'west'}</span>
                <small>{quickMoveStepM} m</small>
              </button>
              <button
                type="button"
                className="precision-move-dialog__control-core"
                onClick={handleSubmitHold}
                disabled={submitting}
                aria-label="Dispatch Hold"
              >
                <span>Center</span>
                <strong>Hold</strong>
                <small>Interrupt and stabilize now</small>
              </button>
              <button
                type="button"
                className="precision-move-dialog__control precision-move-dialog__control--right"
                onClick={() => (
                  interactionMode === 'live_jog'
                    ? dispatchLiveJog({ secondary: quickMoveStepM })
                    : adjustAxis('axisSecondary', quickMoveStepM)
                )}
                disabled={submitting}
              >
                <FaArrowRight aria-hidden="true" />
                <span>{frameConfig.translationKeys[1]}</span>
                <small>+{quickMoveStepM} m</small>
              </button>
              <button
                type="button"
                className="precision-move-dialog__control precision-move-dialog__control--back"
                onClick={() => (
                  interactionMode === 'live_jog'
                    ? dispatchLiveJog({ primary: -quickMoveStepM })
                    : adjustAxis('axisPrimary', -quickMoveStepM)
                )}
                disabled={submitting}
              >
                <FaArrowDown aria-hidden="true" />
                <span>{frameConfig.translationKeys[0] === 'forward' ? 'back' : 'south'}</span>
                <small>{quickMoveStepM} m</small>
              </button>
            </div>

            <div className="precision-move-dialog__controller-rails">
              <div className="precision-move-dialog__rail-group">
                <span>Altitude</span>
                <button
                  type="button"
                  className="precision-move-dialog__control"
                  onClick={() => (
                    interactionMode === 'live_jog'
                      ? dispatchLiveJog({ vertical: quickMoveStepM })
                      : adjustAxis('axisVertical', quickMoveStepM)
                  )}
                  disabled={submitting}
                >
                  <FaArrowUp aria-hidden="true" />
                  <span>Up</span>
                  <small>+{quickMoveStepM} m</small>
                </button>
                <button
                  type="button"
                  className="precision-move-dialog__control"
                  onClick={() => (
                    interactionMode === 'live_jog'
                      ? dispatchLiveJog({ vertical: -quickMoveStepM })
                      : adjustAxis('axisVertical', -quickMoveStepM)
                  )}
                  disabled={submitting}
                >
                  <FaArrowDown aria-hidden="true" />
                  <span>Down</span>
                  <small>{quickMoveStepM} m</small>
                </button>
              </div>
              <div className="precision-move-dialog__rail-group">
                <span>Yaw</span>
                <button
                  type="button"
                  className="precision-move-dialog__control"
                  onClick={() => (
                    interactionMode === 'live_jog'
                      ? dispatchLiveJog({ yawMode: 'relative_delta', yawDegrees: -quickYawStepDeg })
                      : adjustYawDelta(-quickYawStepDeg)
                  )}
                  disabled={submitting}
                >
                  <FaUndo aria-hidden="true" />
                  <span>Yaw left</span>
                  <small>{quickYawStepDeg}°</small>
                </button>
                <button
                  type="button"
                  className="precision-move-dialog__control"
                  onClick={() => (
                    interactionMode === 'live_jog'
                      ? dispatchLiveJog({ yawMode: 'relative_delta', yawDegrees: quickYawStepDeg })
                      : adjustYawDelta(quickYawStepDeg)
                  )}
                  disabled={submitting}
                >
                  <FaRedo aria-hidden="true" />
                  <span>Yaw right</span>
                  <small>{quickYawStepDeg}°</small>
                </button>
              </div>
            </div>
          </div>

          <div className="precision-move-dialog__controller-footer">
            <span className="precision-move-dialog__controller-summary">
              Staged: {stagedVectorSummary}
            </span>
            <button type="button" className="precision-move-dialog__ghost" onClick={resetQuickMove} disabled={submitting}>
              Reset staged move
            </button>
          </div>
        </section>

        <details className="precision-move-dialog__advanced">
          <summary>Manual values</summary>
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
                placeholder={policy?.defaults?.speed_m_s ? String(policy.defaults.speed_m_s) : 'Runtime default'}
                value={formState.speedMps}
                onChange={handleFieldChange('speedMps')}
                disabled={submitting}
              />
            </label>
          </div>

          <section className="precision-move-dialog__subsection">
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
        </details>

        <details className="precision-move-dialog__advanced">
          <summary>Tuning</summary>
          {policyLoading && (
            <p className="precision-move-dialog__hint">Loading runtime defaults…</p>
          )}
          {policyError && (
            <p className="precision-move-dialog__hint">{policyError}</p>
          )}
          {runtimeDefaultsSummary && (
            <div className="precision-move-dialog__defaults-grid" aria-label="Runtime defaults">
              {runtimeDefaultsSummary.map((item) => (
                <div key={item.label} className="precision-move-dialog__default-item">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          )}
          <div className="precision-move-dialog__grid">
            <label>
              <span>Position tolerance (m)</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0.01"
                placeholder={policy?.defaults?.position_tolerance_m ? String(policy.defaults.position_tolerance_m) : 'Runtime default'}
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
                placeholder={policy?.defaults?.yaw_tolerance_deg ? String(policy.defaults.yaw_tolerance_deg) : 'Runtime default'}
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
                placeholder={policy?.defaults?.settle_time_sec ? String(policy.defaults.settle_time_sec) : 'Runtime default'}
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
                placeholder={policy?.defaults?.timeout_sec ? String(policy.defaults.timeout_sec) : 'Runtime default'}
                value={formState.timeoutSec}
                onChange={handleFieldChange('timeoutSec')}
                disabled={submitting}
              />
            </label>
          </div>
        </details>

        <section className="precision-move-dialog__review">
          <div className="precision-move-dialog__review-header">
            <h4>Staged Move</h4>
            <span>{interactionMode === 'live_jog' ? 'Live Jog ignores this staged vector' : `${targetCount} target drone${targetCount === 1 ? '' : 's'}`}</span>
          </div>
          <div className="precision-move-dialog__summary-grid">
            {detailRows.map((detail) => (
              <div key={`${detail.label}-${detail.value}`} className="precision-move-dialog__default-item">
                <span>{detail.label}</span>
                <strong>{detail.value}</strong>
              </div>
            ))}
          </div>
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
          {interactionMode === 'planned' && (
            <button
              type="button"
              className="precision-move-dialog__submit"
              onClick={handleSubmit}
              disabled={submitting || Boolean(validation.error)}
            >
              {submitting ? 'Dispatching…' : 'Dispatch Planned Move'}
            </button>
          )}
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
  liveMonitor: PropTypes.shape({
    commandLabel: PropTypes.string,
    isTerminal: PropTypes.bool,
    acks: PropTypes.shape({
      accepted: PropTypes.number,
      expected: PropTypes.number,
    }),
    progress: PropTypes.shape({
      label: PropTypes.string,
      message: PropTypes.string,
      stage: PropTypes.string,
      active: PropTypes.number,
      completed: PropTypes.number,
    }),
  }),
  submitting: PropTypes.bool,
  onClose: PropTypes.func.isRequired,
  onEditTargetScope: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  onSubmitHold: PropTypes.func.isRequired,
};

export default PrecisionMoveDialog;
