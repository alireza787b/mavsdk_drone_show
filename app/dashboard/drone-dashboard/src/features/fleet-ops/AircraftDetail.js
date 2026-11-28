import React, { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { FaTimes, FaTools } from 'react-icons/fa';

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
  return <aside className="fleet-aircraft-detail" aria-label={`Details for aircraft ${row.posId}`}
    onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
    <header><h2>Aircraft {row.posId}</h2><button className="fleet-tool-icon" type="button" ref={closeButton} aria-label="Close aircraft details" title="Close details" onClick={onClose}><FaTimes /></button></header>
    <dl>
      <div><dt>Hardware</dt><dd>H{row.hwId}</dd></div>
      <div><dt>Connection</dt><dd>{row.presence.label}</dd></div>
      <div><dt>{row.online ? 'Software' : 'Last known software'}</dt><dd>{row.sync.label}
        {row.sync.state !== 'synced' && <small>{row.sync.detail}</small>}</dd></div>
      <div><dt>Revision</dt><dd><code>{row.shortCommit}</code></dd></div>
      <div><dt>Update branch</dt><dd>{row.branch}{row.branchOnly && <small>Same revision as GCS</small>}</dd></div>
      <div><dt>Last checked</dt><dd>{lastCheck > 0 ? new Date(lastCheck).toLocaleString() : 'Unknown'}</dd></div>
      {row.boot.state !== 'unknown' && <div><dt>Startup</dt><dd>{row.boot.detail}</dd></div>}
      {row.nodeSyncRuntime.state !== 'unknown' && <div><dt>Last update</dt><dd>{row.nodeSyncRuntime.detail}</dd></div>}
      {diagnostics.map(([name, item]) => <div key={name}><dt>{name}</dt><dd>{item.label}<small>{item.detail}</small></dd></div>)}
    </dl>
    <Link to={'/maintenance?section=' + section + '&hw_id=' + encodeURIComponent(row.hwId)}><FaTools aria-hidden="true" /> Maintenance</Link>
  </aside>;
}
