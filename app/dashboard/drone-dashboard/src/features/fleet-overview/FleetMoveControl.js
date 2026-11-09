import React, { useEffect, useRef, useState } from 'react';
import PrecisionMoveDialog from '../../components/PrecisionMoveDialog';
import { ConfirmDialog } from '../../components/ui';
import { useCommandActivity } from '../../contexts/CommandActivityContext';
import useCommandDispatch from '../../hooks/useCommandDispatch';
import { DRONE_ACTION_TYPES } from '../../constants/droneConstants';

// Mount for one explicitly inspected aircraft. The existing dialog owns Planned /
// Live Jog interactions; this boundary only freezes scope and tracks submission.
export default function FleetMoveControl({ targetId, targetLabel, runtimeMode, operatorId = '', onClose }) {
  const [scope] = useState(() => ({ id: String(targetId || ''), label: targetLabel || `Aircraft ${targetId}`,
    mode: runtimeMode, operatorId }));
  const current = useRef(null);
  current.current = { id: String(targetId || ''), mode: runtimeMode, operatorId };
  const mounted = useRef(true);
  const recovering = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const matchesScope = () => mounted.current && scope.id && current.current.id === scope.id
    && current.current.mode === scope.mode && current.current.operatorId === scope.operatorId;
  const dispatch = useCommandDispatch(`fleet-move:${scope.id}`, runtimeMode, operatorId);
  const { commandMonitors = [] } = useCommandActivity();
  const pendingKeys = Object.keys(dispatch.pending);
  if (pendingKeys.length && !dispatch.busy) recovering.current = true;
  if (!pendingKeys.length) recovering.current = false;
  const liveMonitor = commandMonitors.filter(monitor =>
    [DRONE_ACTION_TYPES.PRECISION_MOVE, DRONE_ACTION_TYPES.HOLD].includes(Number(monitor.missionType))
    && monitor.targetDrones?.length === 1 && String(monitor.targetDrones[0]) === scope.id)
    .sort((a, b) => Number(b.updatedAtMs) - Number(a.updatedAtMs))[0] || null;
  const close = () => { mounted.current = false; onClose(); };
  const submit = async (action, command, options = {}) => {
    if (!matchesScope() || !dispatch.enabled || dispatch.pending[action]) return false;
    const expected = action === 'move' ? DRONE_ACTION_TYPES.PRECISION_MOVE : DRONE_ACTION_TYPES.HOLD;
    if (Number(command.mission_type) !== expected) return false;
    const payload = { ...command, target_drone_ids: [scope.id], trigger_time: 0 };
    delete payload.target_scope;
    const accepted = await dispatch.submit(action, payload);
    const currentScope = Boolean(matchesScope());
    if (accepted && currentScope && options.closeOnSuccess !== false) close();
    return Boolean(accepted && currentScope);
  };
  const hold = (command, options) => submit('hold', command, options);
  const showRecovery = recovering.current || Boolean(dispatch.error) || !matchesScope() || !dispatch.enabled;
  if (showRecovery) return <ConfirmDialog open appearance="console" title="Precision Move status"
    busy={dispatch.busy} onCancel={close} cancelLabel="Close"
    confirmLabel={pendingKeys.length ? 'Check receipt' : 'Back to move'}
    confirmDisabled={!matchesScope() || !dispatch.enabled}
    onConfirm={() => pendingKeys.length ? dispatch.recover(pendingKeys[0]) : dispatch.clearError()}
    message={<div><strong>{scope.label} · H{scope.id}</strong>
      {dispatch.error && <p role="alert">{dispatch.error}</p>}
      {(!matchesScope() || !dispatch.enabled) && <p>Aircraft or runtime context unavailable or changed. Close and inspect again.</p>}
      {pendingKeys.length > 0 && <><p>Receipt unconfirmed: {pendingKeys.join(', ')}. Checking does not resend movement.</p>
        <button type="button" className="operator-button" disabled={dispatch.busy || !dispatch.enabled || !matchesScope() || Boolean(dispatch.pending.hold)}
          onClick={() => hold({ mission_type: DRONE_ACTION_TYPES.HOLD, trigger_time: 0,
            uiMeta: { operatorLabel: 'Hold' } }, { closeOnSuccess: false })}>Hold now</button></>}
    </div>} />;
  return <PrecisionMoveDialog isOpen targetLabel={scope.label} targetDescriptor={`Aircraft H${scope.id}`}
    targetCount={1} scopeLocked liveMonitor={liveMonitor} submitting={dispatch.busy} onClose={close}
    onSubmit={(command, options) => submit('move', command, options)} onSubmitHold={hold} />;
}
