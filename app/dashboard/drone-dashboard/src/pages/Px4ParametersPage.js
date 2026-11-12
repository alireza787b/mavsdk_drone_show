import React, { useEffect, useRef, useState } from 'react';
import { PageShell, PageActionBar, OperatorNotice } from '../components/ui';
import { getBackendURL } from '../config/apiConfig';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import { diffPx4ParamSnapshot, getPx4ParamProfile, importQgcParameterFile } from '../services/px4ParamsApiService';
import { buildQgcParameterFile } from '../utilities/px4ParameterFiles';
import { buildMdsParameterProfileFile } from '../utilities/px4ParameterProfiles';
import { parameterKey, snapshotAge, snapshotState } from '../utilities/px4ParameterValues';
import useParameterResources from '../features/px4-parameters/useParameterResources';
import useParameterWorkspace, { parameterError } from '../features/px4-parameters/useParameterWorkspace';
import ActionReview, { buildActionStorageKey, readPendingAction, readPendingActions } from '../features/fleet-overview/ActionReview';
import ParameterBrowser from '../components/px4/ParameterBrowser';
import Px4ParamInspector from '../components/px4/Px4ParamInspector';
import Px4ParamProfilePanel from '../components/px4/Px4ParamProfilePanel';
import ParameterReview, { describeAircraft } from '../components/px4/ParameterReview';
import ParameterActivity from '../components/px4/ParameterActivity';
import { AircraftChooser, ManualParameterEntry } from '../components/px4/ParameterTools';
import '../styles/Px4ParametersPage.css';

function download({ filename, text }) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click();
  URL.revokeObjectURL(url);
}

export default function Px4ParametersPage({ runtimeMode = 'unknown', operatorId = '' }) {
  const context = `${getBackendURL()}:${runtimeMode}:${operatorId || 'browser-session'}`;
  return <ParameterWorkspace key={context} context={context} runtimeMode={runtimeMode} />;
}

function ParameterWorkspace({ context, runtimeMode }) {
  const resources = useParameterResources(context);
  const [tab, setTab] = useState('parameters'), [viewId, setViewId] = useState('');
  const [chooser, setChooser] = useState(false), [manual, setManual] = useState(false), [reviewOpen, setReviewOpen] = useState(false);
  const [inspectedKey, setInspectedKey] = useState(''), [inspectorOpen, setInspectorOpen] = useState(false);
  const [profileId, setProfileId] = useState(''), [profile, setProfile] = useState(null), [profileBusy, setProfileBusy] = useState(false);
  const [profileDiff, setProfileDiff] = useState(null), [compareBusy, setCompareBusy] = useState(false);
  const [fileBusy, setFileBusy] = useState(false), [notice, setNotice] = useState(null), [reboot, setReboot] = useState(null);
  const fileInput = useRef(null), liveContext = useRef(context), importGeneration = useRef(0), comparisonGeneration = useRef(0);
  const storageKey = `mds:px4-parameters:v2:${context}`;
  const rebootPrefix = `${storageKey}:reboot`;
  const [pendingReboots, setPendingReboots] = useState(() => readPendingActions(rebootPrefix));
  const workspace = useParameterWorkspace({ viewId, componentId: resources.policy?.mutations?.supported_component_ids?.[0] || 1, storageKey });
  const snapshot = workspace.snapshot, aircraft = resources.aircraft.find(item => item.id === viewId);
  const row = snapshot?.rows?.find(item => parameterKey(item) === inspectedKey);
  const knownRuntime = ['real', 'sitl'].includes(runtimeMode);
  useEffect(() => { liveContext.current = context; return () => { liveContext.current = null; importGeneration.current += 1; comparisonGeneration.current += 1; }; }, [context]);
  useEffect(() => {
    if (!profileId && resources.profiles.length) setProfileId(resources.profiles[0].profile_id);
  }, [profileId, resources.profiles]);
  useEffect(() => {
    let live = true;
    setProfile(null); setProfileDiff(null);
    if (!profileId) return undefined;
    setProfileBusy(true);
    getPx4ParamProfile(profileId).then(({ data }) => { if (live) setProfile(data); })
      .catch(error => { if (live) setNotice({ tone: 'warning', title: 'Profile unavailable', detail: parameterError(error) }); })
      .finally(() => { if (live) setProfileBusy(false); });
    return () => { live = false; };
  }, [profileId]);
  useEffect(() => { setProfileDiff(null); comparisonGeneration.current += 1; }, [profileId, viewId, snapshot?.snapshot?.snapshot_id]);
  useEffect(() => { if (!workspace.draft) setReviewOpen(false); }, [workspace.draft]);

  const stage = next => {
    const staged = workspace.stage(next);
    if (staged) setReviewOpen(true);
    return staged;
  };
  const chooseAircraft = id => {
    setViewId(id); setInspectorOpen(false); setInspectedKey('');
    // Only inspection changes. Existing drafts and reviewed target IDs stay fixed.
    importGeneration.current += 1;
  };
  const importFile = async event => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || !viewId || !snapshot) return;
    const boundId = viewId, generation = ++importGeneration.current;
    setFileBusy(true); setNotice(null);
    try {
      const { data } = await importQgcParameterFile(await file.text());
      if (liveContext.current !== context || generation !== importGeneration.current) return;
      stage({ title: file.name, source: 'qgc_import', entries: data.entries, hwIds: [boundId], excludedHwIds: [],
        importNotes: { skippedCount: data.skipped_count || 0, warnings: data.warnings || [] },
        originHwId: boundId, originSnapshotId: snapshot.snapshot.snapshot_id });
    } catch (error) { if (liveContext.current === context && generation === importGeneration.current) setNotice({ tone: 'warning', title: 'Import failed', detail: parameterError(error) }); }
    finally { if (liveContext.current === context) setFileBusy(false); }
  };
  const compareProfile = async () => {
    if (!profile || !snapshot) return;
    const generation = ++comparisonGeneration.current;
    setCompareBusy(true);
    try {
      const { data } = await diffPx4ParamSnapshot({ snapshotId: snapshot.snapshot.snapshot_id, desiredEntries: profile.entries, includeUnchanged: false });
      if (liveContext.current === context && generation === comparisonGeneration.current) setProfileDiff(data);
    } catch (error) { if (liveContext.current === context) setNotice({ tone: 'warning', title: 'Compare failed', detail: parameterError(error) }); }
    finally { if (liveContext.current === context) setCompareBusy(false); }
  };
  const exportSnapshot = () => {
    const bundle = buildQgcParameterFile(snapshot); download(bundle);
    if (bundle.skippedRows.length) setNotice({ tone: 'info', title: 'Export complete', detail: `${bundle.skippedRows.length} non-QGC values omitted.` });
  };
  const openReboot = saved => {
    if (saved) { setReboot({ storageKey: saved.storageKey, command: { ...saved.command, recover: true } }); return; }
    if (!viewId) return;
    const command = { mission_type: DRONE_ACTION_TYPES.REBOOT_FC, target_drone_ids: [viewId], trigger_time: 0,
      uiMeta: { operatorLabel: 'Reboot PX4', targetLabel: describeAircraft(resources.aircraft, viewId) } };
    const key = buildActionStorageKey(rebootPrefix, command), pending = readPendingAction(key);
    setReboot({ storageKey: key, command: pending ? { ...pending, recover: true } : command });
  };
  const blockEdit = !resources.policy ? 'Write policy unavailable.' : resources.policy.mutations?.require_disarmed && aircraft?.armed === true ? 'Aircraft is armed. Parameter writes are blocked.' : '';
  const rebootBlocked = !viewId || !knownRuntime || aircraft?.armed === true || !['online', 'degraded'].includes(aircraft?.runtime.level);
  return <PageShell className="px4-parameters-page operator-console" title="PX4 Parameters" docsRoute="/px4-parameters"
    status={<span className="px4-runtime">{runtimeMode.toUpperCase()}</span>}>
    <div className="px4-workspace-tabs" role="tablist" aria-label="Parameter workspace">{['parameters', 'profiles'].map(key => <button key={key} type="button" role="tab" id={`px4-tab-${key}`}
      aria-controls={`px4-panel-${key}`} aria-selected={tab === key} onClick={() => setTab(key)}>{key === 'parameters' ? 'Parameters' : 'Profiles'}</button>)}</div>
    <section className="px4-identity-strip" aria-label="Viewed aircraft">
      <div className="px4-viewed-aircraft"><span className="px4-muted">Viewing</span><button type="button" className="operator-button operator-button--ghost" aria-label="Choose aircraft" onClick={() => setChooser(true)}>{viewId ? describeAircraft(resources.aircraft, viewId) : 'Choose aircraft'} ▾</button>
        {viewId && <span>{aircraft?.runtime.label || 'Identity unavailable'}</span>}</div>
      <span className={snapshotState(snapshot?.snapshot, resources.now) === 'Snapshot stale' ? 'px4-stale' : 'px4-muted'} title={snapshotAge(snapshot?.snapshot, resources.now)}>{snapshotState(snapshot?.snapshot, resources.now)}</span>
      <PageActionBar primary={<button type="button" className="operator-button operator-button--ghost" disabled={!viewId || workspace.snapshotBusy} onClick={workspace.refresh}>{workspace.snapshotBusy ? 'Refreshing…' : 'Refresh'}</button>}
        secondary={[
          <button key="import" type="button" className="operator-button operator-button--ghost" disabled={!snapshot || fileBusy} onClick={() => fileInput.current?.click()}>{fileBusy ? 'Importing…' : 'Import QGC'}</button>,
          <button key="export" type="button" className="operator-button operator-button--ghost" disabled={!snapshot} onClick={exportSnapshot}>Export QGC</button>,
          <button key="manual" type="button" className="operator-button operator-button--ghost" onClick={() => setManual(true)}>Manual change</button>,
          <button key="reboot" type="button" className="operator-button operator-button--ghost" disabled={rebootBlocked} title={rebootBlocked ? 'Requires a linked, disarmed aircraft and known runtime mode.' : undefined} onClick={() => openReboot()}>Reboot PX4</button>,
        ]} />
      <input ref={fileInput} type="file" accept=".params,.txt,.tsv,.csv" aria-label="Import QGC parameter file" className="px4-hidden-input" onChange={importFile} />
    </section>
    {resources.error && <OperatorNotice tone="warning" title="Fleet evidence unavailable">Last observations are aging. Parameter snapshots have their own freshness.</OperatorNotice>}
    {workspace.snapshotError && <OperatorNotice tone="warning" title="Snapshot refresh failed">{workspace.snapshotError}</OperatorNotice>}
    {resources.policyError && <OperatorNotice tone="warning" title="Write policy unavailable">Inspection remains available.</OperatorNotice>}
    {notice && <OperatorNotice tone={notice.tone} title={notice.title} action={<button type="button" className="operator-button operator-button--ghost" onClick={() => setNotice(null)}>Dismiss</button>}>{notice.detail}</OperatorNotice>}
    {workspace.error && !reviewOpen && <OperatorNotice tone="warning" title="Draft unchanged">{workspace.error}</OperatorNotice>}
    <section id={`px4-panel-${tab}`} role="tabpanel" aria-labelledby={`px4-tab-${tab}`}>
      {tab === 'parameters' ? <ParameterBrowser rows={snapshot?.rows || []} busy={workspace.snapshotBusy} selectedKey={inspectedKey}
        aircraftId={viewId} readError={workspace.snapshotError} onRefresh={workspace.refresh}
        sessionChanges={workspace.sessionChanges} onInspect={entry => { setInspectedKey(parameterKey(entry)); setInspectorOpen(true); }} />
        : <><div className="px4-profile-toolbar"><label>Profile<select aria-label="Saved PX4 profile" value={profileId} onChange={event => setProfileId(event.target.value)}><option value="">Choose profile…</option>{resources.profiles.map(item => <option key={item.profile_id} value={item.profile_id}>{item.name}</option>)}</select></label>
          {resources.profilesError && <span>Profile library unavailable.</span>}</div>
          <Px4ParamProfilePanel profile={profile} loading={profileBusy} compareTargetLabel={viewId && snapshot ? describeAircraft(resources.aircraft, viewId) : ''}
            compareResult={profileDiff} compareLoading={compareBusy} onPreviewDiff={compareProfile}
            onReview={() => stage({ title: profile.name, source: 'mds_profile', profileId: profile.profile_id, entries: profile.entries, hwIds: [], excludedHwIds: [] })}
            onExportProfile={() => download(buildMdsParameterProfileFile(profile))} /></>}
    </section>
    {snapshot && <details className="px4-source-details"><summary>Snapshot & reference</summary><dl className="px4-facts"><dt>Fetched</dt><dd>{snapshotAge(snapshot.snapshot, resources.now)}</dd>
      <dt>Source</dt><dd>Aircraft H{snapshot.snapshot.hw_id} · Component {snapshot.snapshot.component_id}</dd><dt>Metadata</dt><dd>{String(snapshot.snapshot.metadata_quality || 'unknown').replace(/_/g, ' ')}</dd>
      <dt>PX4 reference</dt><dd>{resources.policy?.docs?.version || 'Unknown version'}</dd><dt>Write policy</dt><dd>{resources.policy ? resources.policy.mutations?.require_disarmed ? 'Disarmed required' : 'Native policy' : 'Unavailable'}</dd></dl>
      {snapshot.snapshot.metadata_warning && <p>{snapshot.snapshot.metadata_warning}</p>}</details>}
    <ParameterActivity receipts={workspace.receipts} aircraft={resources.aircraft} onLookup={workspace.lookup} storageError={workspace.storageError} />
    {!!pendingReboots.length && <details className="px4-activity"><summary>Unconfirmed PX4 reboot · {pendingReboots.length}</summary>{pendingReboots.map(item => <button type="button" key={item.storageKey} className="operator-button operator-button--ghost" onClick={() => openReboot(item)}>Check reboot · {item.command.target_drone_ids.map(id => `H${id}`).join(', ')}</button>)}</details>}
    <footer className="px4-draft-rail" aria-label="Parameter draft">{workspace.draft ? <><span>{workspace.draft.entries.length} proposed · {workspace.draft.hwIds.length} targets · {workspace.draft.title}</span>
      <button type="button" className="operator-button operator-button--primary" onClick={() => setReviewOpen(true)}>Review changes</button>
      <button type="button" className="operator-button operator-button--ghost" onClick={workspace.discard}>Discard draft</button></> : <span>No pending changes</span>}</footer>
    {chooser && <AircraftChooser aircraft={resources.aircraft} selectedId={viewId} onChoose={chooseAircraft} onClose={() => setChooser(false)} />}
    {manual && <ManualParameterEntry componentIds={resources.policy?.mutations?.supported_component_ids || [1]} onClose={() => setManual(false)}
      onStage={entry => stage({ title: 'Manual change', source: 'manual', entries: [entry], hwIds: [], excludedHwIds: [] })} />}
    {row && inspectorOpen && <Px4ParamInspector key={`${viewId}:${inspectedKey}`} row={row} aircraftLabel={describeAircraft(resources.aircraft, viewId)} onClose={() => setInspectorOpen(false)} blockedReason={blockEdit}
      snapshotLabel={snapshotState(snapshot.snapshot, resources.now)} snapshotAgeLabel={snapshotAge(snapshot.snapshot, resources.now)}
      onStage={entry => stage({ title: 'Manual changes', source: 'manual', entries: [entry], hwIds: [viewId], excludedHwIds: [], originHwId: viewId, originSnapshotId: snapshot.snapshot.snapshot_id })} />}
    {workspace.draft && reviewOpen && !inspectorOpen && !manual && <ParameterReview workspace={workspace} aircraft={resources.aircraft} clusters={resources.clusters} now={resources.now} knownRuntime={knownRuntime} onClose={() => setReviewOpen(false)} />}
    {reboot && <ActionReview key={reboot.storageKey} intent={reboot.command} storageKey={reboot.storageKey} aircraft={resources.aircraft} runtimeMode={runtimeMode}
      onClose={() => { setReboot(null); setPendingReboots(readPendingActions(rebootPrefix)); }} onResolved={() => setPendingReboots(readPendingActions(rebootPrefix))} />}
  </PageShell>;
}
