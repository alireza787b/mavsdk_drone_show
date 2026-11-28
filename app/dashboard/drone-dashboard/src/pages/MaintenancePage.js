import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { FaArrowLeft, FaChevronRight, FaKey, FaSatelliteDish, FaServer, FaTools, FaWifi } from 'react-icons/fa';
import { PageShell } from '../components/ui';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { classifyGitAuth, formatRepoAccessMode } from '../utilities/fleetOpsViewModel';
import '../styles/MaintenancePage.css';

const tools = [
  { to: '/fleet-ops/wifi', title: 'Wi-Fi profiles', Icon: FaWifi },
  { to: '/fleet-ops/mavlink', title: 'MAVLink routing', Icon: FaSatelliteDish },
  { to: '?section=access', title: 'Repository access', Icon: FaKey },
  { to: '?section=sidecars', title: 'Aircraft services', Icon: FaTools },
  { to: '/runtime-admin', title: 'GCS runtime', Icon: FaServer },
];

function MaintenanceCredential() {
  const [status, setStatus] = useState('');
  function storeToken(form, clear) {
    const field = form.elements.token;
    try {
      if (clear) {
        window.sessionStorage.removeItem('fleetOpsMutationToken');
        setStatus('Cleared');
      } else if (field.value) {
        window.sessionStorage.setItem('fleetOpsMutationToken', field.value);
        setStatus('Saved for this tab');
      }
      field.value = '';
    } catch {
      setStatus('Browser storage unavailable');
    }
  }
  return <details className="maintenance-credential">
    <summary>Maintenance token</summary>
    <form onSubmit={event => { event.preventDefault(); storeToken(event.currentTarget, false); }}>
      <label>Token for this tab <input type="password" name="token" autoComplete="off" /></label>
      <button type="submit">Save</button>
      <button type="button" onClick={event => storeToken(event.currentTarget.form, true)}>Clear</button>
      <output>{status}</output>
    </form>
  </details>;
}

function NodeDiagnostics({ access, hwId }) {
  const { data, loading, error } = useFetch(GCS_ROUTE_KEYS.gitStatus);
  const rows = Object.values(data?.git_status || {})
    .filter(row => !hwId || String(row.hw_id) === hwId)
    .sort((left, right) => left.pos_id - right.pos_id);
  return <section className="maintenance-diagnostics" aria-label={access ? 'Repository access' : 'Aircraft services'}>
    {error && <p role="status">Software reports unavailable</p>}
    {loading && !data && <p role="status">Loading aircraft…</p>}
    {rows.length > 0 ? <table>
      <thead><tr><th>Aircraft</th>{access
        ? <><th>Access</th><th>Authentication</th><th>Update branch</th></>
        : <><th>MAVLink</th><th>Wi-Fi</th><th>Last sync</th></>}</tr></thead>
      <tbody>{rows.map(row => {
        const branchNote = row.in_sync_with_gcs && row.branch && row.branch !== 'unknown'
          && data.gcs_status?.branch && row.branch !== data.gcs_status.branch;
        return <tr key={row.hw_id}>
          <th scope="row">P{row.pos_id} · H{row.hw_id}</th>
          {access ? <>
            <td>{formatRepoAccessMode(row.repo_access_mode)}</td>
            <td>{classifyGitAuth(row).label}</td>
            <td>{row.branch || 'Unknown'} {branchNote &&
              <Link to={'/fleet-ops?hw_id=' + encodeURIComponent(row.hw_id)} aria-label={'Review branch alignment for H' + row.hw_id}>Align branch</Link>}</td>
          </> : <>
            <td>{row.mavlink_runtime?.router_service_status || 'Unknown'}</td>
            <td>{row.connectivity_runtime?.backend === 'none' ? 'Unmanaged' : row.connectivity_runtime?.service_status || 'Unknown'}</td>
            <td>{row.git_sync_runtime?.status || 'Unknown'}</td>
          </>}
        </tr>;
      })}</tbody>
    </table> : !loading && !error && <p>No aircraft reports</p>}
    {access && <MaintenanceCredential />}
  </section>;
}

export default function MaintenancePage() {
  const [params] = useSearchParams();
  const section = params.get('section') || params.get('tab');
  const hwId = params.get('hw_id');
  const access = section === 'access';
  const diagnostics = access || section === 'sidecars';
  return <PageShell title={diagnostics ? (access ? 'Repository access' : 'Aircraft services') : 'Maintenance'}
    className="maintenance-page" icon={<FaTools />} docsRoute="/maintenance"
    actions={<Link className="maintenance-back" to={diagnostics ? (hwId ? '/maintenance?hw_id=' + encodeURIComponent(hwId) : '/maintenance') : '/fleet-ops'}>
      <FaArrowLeft aria-hidden="true" /> {diagnostics ? 'Maintenance' : 'Fleet Ops'}
    </Link>}>
    {diagnostics ? <NodeDiagnostics access={access} hwId={hwId} /> :
      <nav className="maintenance-tools" aria-label="Maintenance tools">{tools.map(({ to, title, Icon }) =>
        <Link key={to} to={hwId && to.startsWith('?') ? to + '&hw_id=' + encodeURIComponent(hwId) : to}><Icon aria-hidden="true" /><strong>{title}</strong><FaChevronRight aria-hidden="true" /></Link>)}
      </nav>}
  </PageShell>;
}
