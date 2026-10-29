import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import '../../styles/TrajectoryDialogPortal.css';

let openDialogs = 0;
let previousOverflow = '';

// Map controls and transformed workspace ancestors must never cover a dialog.
// One body-level host owns stacking and background scrolling for every editor
// dialog; each child retains its existing fields and action semantics.
export default function TrajectoryDialogPortal({ children }) {
  useEffect(() => {
    const previousFocus = document.activeElement;
    if (openDialogs++ === 0) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    }
    return () => {
      if (--openDialogs === 0) document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus?.();
    };
  }, []);

  return createPortal(<div className="trajectory-dialog-host">{children}</div>, document.body);
}
