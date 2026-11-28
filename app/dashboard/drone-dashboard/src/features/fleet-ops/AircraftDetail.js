import React, { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { FaTimes, FaTools } from 'react-icons/fa';
import InfoHint from '../../components/InfoHint';

export default function AircraftDetail({ row, onClose }) {
  const closeButton = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    closeButton.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  const diagnostics = [['Access', row.auth], ['MAVLink', row.mavlink], ['Wi-Fi', row.connectivity]]
    .filter(([, item]) => item.tone === 'warning' || item.tone === 'danger');
  const section = diagnostics.some(([name]) => name !== 'Access') ? 'sidecars' : 'access';
  const lastCheck = Number(row.gitStatus?.last_check);
  const facts = [
    ['Hardware', `H${row.hwId}`],
    ['Connection', row.presence.label, row.presence.detail, row.presence.tone],
    [row.online ? 'Software' : 'Last known software', row.sync.label, row.branchOnly ? '' : row.sync.detail, row.online ? row.sync.tone : 'muted'],
    ['Revision', <code>{row.shortCommit}</code>],
    ['Update branch', row.branch, row.branchOnly && 'Same revision as GCS. The aircraft follows a different update branch.'],
    ['Last checked', lastCheck > 0 ? new Date(lastCheck).toLocaleString() : 'Unknown'],
    ...[['Startup', row.boot], ['Last update', row.nodeSyncRuntime], ...diagnostics]
      .filter(([, item]) => item.state !== 'unknown')
      .map(([name, item]) => [name, item.label, item.detail, item.tone]),
  ];
  return <aside className="fleet-aircraft-detail" aria-label={`Details for aircraft ${row.posId}`}
    onKeyDown={event => {
      if (event.key === 'Escape' && !event.currentTarget.querySelector('[role="tooltip"]')) onClose();
    }}>
    <header><h2>Aircraft {row.posId}</h2><button className="fleet-tool-icon" type="button" ref={closeButton} aria-label="Close aircraft details" title="Close details" onClick={onClose}><FaTimes /></button></header>
    <dl>
      {facts.map(([name, value, detail, tone = '']) => <div key={name}>
        <dt>{name}{detail && <InfoHint hoverable placement="bottom" label={`About ${name.toLowerCase()}`} content={detail} />}</dt>
        <dd data-tone={tone}>{value}</dd>
      </div>)}
    </dl>
    <Link to={'/maintenance?section=' + section + '&hw_id=' + encodeURIComponent(row.hwId)}><FaTools aria-hidden="true" /> Maintenance</Link>
  </aside>;
}
