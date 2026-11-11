import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import { MdCloudUpload, MdDescription, MdInsights, MdRoute } from 'react-icons/md';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { useTheme } from '../contexts/ThemeContext';
import CustomShowOperate from '../components/CustomShowOperate';
import { extractApiErrorMessage } from '../services/apiError';
import { buildGcsUrl, GCS_ROUTE_KEYS, importCustomShowResponse, postGcsResource } from '../services/gcsApiService';
import { MetricStrip, OperatorNotice, PageShell, StatusBadge } from '../components/ui';
import '../styles/DroneShowWorkspace.css';
import '../styles/CustomShowWorkspace.css';

const COLUMNS = ['t', 'px', 'py', 'pz', 'vx', 'vy', 'vz', 'ax', 'ay', 'az', 'yaw', 'mode'];
const duration = value => value == null || !Number.isFinite(Number(value)) ? '—'
  : `${Math.floor(Math.round(Number(value)) / 60)}:${String(Math.round(Number(value)) % 60).padStart(2, '0')}`;

export default function CustomShowWorkspace({ runtimeMode = 'unknown' }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'setup' ? 'setup' : 'operate';
  const setTab = next => setParams(previous => { const result = new URLSearchParams(previous); result.set('tab', next); return result; });
  const [selectedFile, setSelectedFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [warnings, setWarnings] = useState([]);
  const [imageFailed, setImageFailed] = useState(false);
  const input = useRef(null);
  const { theme } = useTheme();
  const infoState = useGcsResourcePolling(GCS_ROUTE_KEYS.customShowInfo, 15000, refreshKey);
  const info = infoState.data;
  const loaded = Boolean(info?.exists);
  const needsPreview = loaded && (!info.preview_exists || (theme === 'dark' && info.preview_themes?.dark === false));
  useEffect(() => setImageFailed(false), [info?.sha256, refreshKey, theme]);
  const chooseFile = event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) { setSelectedFile(null); toast.error('Choose a CSV file.'); return; }
    setSelectedFile(file);
  };
  const upload = async () => {
    if (!selectedFile || busy) return;
    const form = new FormData(); form.append('file', selectedFile);
    setBusy(true); setWarnings([]);
    try {
      const { data } = await importCustomShowResponse(form);
      if (!data?.success) throw new Error(data?.detail || data?.message || 'CSV import failed');
      setWarnings(data.warnings || []); setSelectedFile(null);
      if (input.current) input.current.value = '';
      setRefreshKey(previous => previous + 1);
      toast.success('CSV loaded. Review the path before launch.');
    } catch (error) { toast.error(await extractApiErrorMessage(error, 'CSV import failed.')); }
    finally { setBusy(false); }
  };
  const refreshPreview = async () => {
    if (busy) return;
    setBusy(true);
    try { await postGcsResource(GCS_ROUTE_KEYS.customShowImage, {}); setRefreshKey(previous => previous + 1); }
    catch (error) { toast.error(await extractApiErrorMessage(error, 'Preview refresh failed.')); }
    finally { setBusy(false); }
  };
  const preview = <figure className="drone-show-workspace__preview-wrap">
    <figcaption>Path · local launch frame</figcaption>
    {loaded && info.preview_exists && !needsPreview && !imageFailed
      ? <img className="drone-show-workspace__preview" alt="Custom CSV path and height profile"
        src={`${buildGcsUrl(GCS_ROUTE_KEYS.customShowImage)}?theme=${theme}&revision=${encodeURIComponent(info.sha256 || refreshKey)}&refresh=${refreshKey}`}
        onError={() => setImageFailed(true)} />
      : <div className="custom-show-page__empty-preview"><MdRoute aria-hidden="true" />
        <span>{loaded ? 'Preview unavailable' : 'Load a CSV to preview the path'}</span>
        {loaded && <button type="button" className="operator-button" disabled={busy} onClick={refreshPreview}>Refresh preview</button>}
      </div>}
  </figure>;
  return <PageShell className="drone-show-workspace custom-show-page operator-console" title="Custom Show" docsRoute="/custom-show"
    status={<StatusBadge tone={loaded ? 'info' : 'muted'}>{loaded ? 'CSV loaded' : 'No CSV'}</StatusBadge>}>
    <div className="drone-show-workspace__tabs" role="tablist" aria-label="Custom CSV workspace">
      {['operate', 'setup'].map(key => <button type="button" role="tab" key={key} id={`custom-tab-${key}`} aria-controls={`custom-panel-${key}`}
        aria-selected={tab === key} className={tab === key ? 'is-active' : ''} onClick={() => setTab(key)}>{key === 'operate' ? 'Operate' : 'Design / Setup'}</button>)}
    </div>
    {infoState.error && infoState.error.response?.status !== 404 && <OperatorNotice tone="warning" title="CSV information unavailable">Refresh the connection before launch.</OperatorNotice>}
    {loaded && <section className="drone-show-workspace__summary" aria-label="Loaded custom show">
      <div className="drone-show-workspace__summary-heading"><strong><MdDescription aria-hidden="true" /> {info.filename}</strong><span className="drone-show-workspace__summary-state">Local frame</span></div>
      <MetricStrip className="drone-show-workspace__metrics" label="Custom show summary" items={[
        { key: 'duration', label: 'Duration', value: duration(info.duration_sec), icon: <MdInsights /> },
        { key: 'height', label: 'Peak height', value: info.max_altitude == null ? '—' : `${Number(info.max_altitude).toFixed(1)} m`, icon: <MdRoute /> },
        { key: 'samples', label: 'Samples', value: info.row_count ?? '—', icon: <MdDescription /> },
      ]} />
    </section>}
    <div id="custom-panel-operate" role="tabpanel" aria-labelledby="custom-tab-operate" hidden={tab !== 'operate'}>
      <CustomShowOperate infoState={infoState} runtimeMode={runtimeMode} onSetup={() => setTab('setup')} />
      {tab === 'operate' && loaded && <details className="drone-show-workspace__evidence-panel"><summary>Path preview</summary>{preview}</details>}
    </div>
    <section id="custom-panel-setup" role="tabpanel" aria-labelledby="custom-tab-setup" hidden={tab !== 'setup'}>
      {tab === 'setup' && <div className="custom-show-page__setup">
        <section className="custom-show-page__import" aria-labelledby="custom-import-title">
          <header className="drone-show-workspace__setup-intro"><h2 id="custom-import-title">Load path</h2><Link to="/drone-show?tab=setup">SkyBrush ZIP →</Link></header>
          <p className="custom-show-page__frame-note">One CSV · same path from each aircraft’s launch point</p>
          <input ref={input} type="file" accept=".csv,text/csv" hidden aria-label="CSV file" onChange={chooseFile} disabled={busy} />
          <div className="custom-show-page__upload"><button type="button" className="operator-button" onClick={() => input.current?.click()} disabled={busy}><MdDescription aria-hidden="true" />{selectedFile?.name || 'Choose CSV'}</button>
            <button type="button" className="operator-button operator-button--primary" onClick={upload} disabled={!selectedFile || busy}><MdCloudUpload aria-hidden="true" />{busy ? 'Processing…' : 'Validate & load'}</button></div>
          {warnings.length > 0 && <OperatorNotice tone="warning" title="Import notes">{warnings.map(warning => <p key={warning}>{warning}</p>)}</OperatorNotice>}
          <details className="custom-show-page__requirements"><summary>CSV format</summary><p>Local-frame protocol CSV. No shared-origin correction or SkyBrush conversion.</p><code>{(info?.required_columns || COLUMNS).join(', ')}</code></details>
          {loaded && <button type="button" className="operator-button" onClick={() => setTab('operate')}>Continue to Operate →</button>}
        </section>
        {preview}
      </div>}
    </section>
  </PageShell>;
}
