import React from 'react';
import { OperatorNotice } from './ui';
import { formatCommandAbsoluteTime } from '../utilities/commandScheduling';
import { formatShowStart } from '../utilities/droneShowWorkspace';

export default function ShowReceiptRecovery({ dispatch }) {
  return <>
    {dispatch.error && <OperatorNotice tone="warning" title="Check command status">{dispatch.error}</OperatorNotice>}
    {Object.entries(dispatch.pending).map(([action, request]) => <OperatorNotice key={action} tone="warning"
      title={`${action} receipt unconfirmed`} action={<button type="button" className="operator-button"
        disabled={dispatch.busy || !dispatch.enabled} onClick={() => dispatch.recover(action)}>Check receipt</button>}>
      H{request.command.target_drone_ids.join(' · H')} · {[1, 3].includes(Number(request.command.mission_type))
        ? formatShowStart(request.command.trigger_time) : formatCommandAbsoluteTime(request.command.trigger_time)}.
      {' '}Checking the receipt does not resend this command.
    </OperatorNotice>)}
  </>;
}
