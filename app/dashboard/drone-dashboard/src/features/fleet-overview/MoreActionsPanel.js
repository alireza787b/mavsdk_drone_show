import React, { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import DroneActions from '../../components/DroneActions';
import { DRONE_ACTION_TYPES } from '../../constants/droneConstants';
import './MoreActionsPanel.css';

// The caller freezes the target identity set. This panel only creates intents;
// it never discovers aircraft, modifies selection, or submits to an API.
export default function MoreActionsPanel({
  targetCount, targetLabel, runtimeMode, referenceNowMs,
  onSendCommand, onRequestPrecisionMove, canPrecisionMove = false, onClose,
}) {
  const dialogRef = useRef(null);
  const titleId = useId();
  const scopeId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const dialog = dialogRef.current;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector('button')?.focus();
    return () => {
      dialog.close?.();
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const dialog = dialogRef.current;
    const collapsed = Array.from(dialog.querySelectorAll('details:not([open])'));
    const controls = Array.from(dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [href], [tabindex="0"]'))
      .filter((element) => !element.closest('[hidden]') && !collapsed.some((details) => details.contains(element) && element !== details.querySelector('summary')));
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault(); first?.focus();
    }
  };

  return createPortal(<dialog ref={dialogRef} className="fleet-more-panel" aria-modal="true"
    aria-labelledby={titleId} aria-describedby={scopeId} onKeyDown={handleKeyDown}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="fleet-more-panel__surface">
      <header><h2 id={titleId}>More actions</h2><button type="button" onClick={onClose} aria-label="Close more actions">×</button></header>
      <p id={scopeId} className="fleet-more-panel__scope"><strong>{targetCount} aircraft</strong><span>{targetLabel}</span><span>{String(runtimeMode || 'unknown').toUpperCase()}</span></p>
      <DroneActions actionTypes={DRONE_ACTION_TYPES} includeFlightControls={false} targetCount={targetCount}
        runtimeMode={runtimeMode} referenceNowMs={referenceNowMs} onSendCommand={onSendCommand}
        onRequestPrecisionMove={onRequestPrecisionMove} canPrecisionMove={canPrecisionMove} />
    </div>
  </dialog>, document.body);
}
