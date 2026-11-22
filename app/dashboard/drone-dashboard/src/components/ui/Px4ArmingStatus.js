import React, { useEffect, useMemo, useState } from 'react';
import { FaCheckCircle, FaInfoCircle, FaRedo, FaStopCircle } from 'react-icons/fa';
import { useObservationResource } from '../../contexts/ObservationContext';
import { normalizeTelemetryResponse } from '../../constants/fieldMappings';
import { unwrapFleetTelemetryPayload, fetchGcsResource } from '../../services/gcsApiService';
import useObservationClock from '../../hooks/useObservationClock';
import { px4ArmingVerdict } from '../../utilities/px4Arming';
import '../../styles/Px4ArmingStatus.css';

export function usePx4Fleet(enabled = true) {
  const resource = useObservationResource(enabled ? 'telemetry' : null, '', true);
  const now = useObservationClock();
  const rows = useMemo(() => normalizeTelemetryResponse(unwrapFleetTelemetryPayload(resource.response?.data || {}), {
    receivedAtMs: resource.receivedAtMs,
    serverNowMs: resource.response?.headers?.['x-mds-server-time'] ?? resource.response?.data?.timestamp,
  }), [resource.response, resource.receivedAtMs]);
  return { rows, now, receivedAt: resource.receivedAtMs, refresh: resource.refresh };
}

function useCurrentVerdict(verdict) {
  const [, expire] = useState(0);
  const deadline = verdict?.local_deadline_ms;
  useEffect(() => {
    if (!Number.isFinite(deadline) || deadline <= performance.now()) return undefined;
    const timer = setTimeout(() => expire(value => value + 1), Math.ceil(deadline - performance.now()));
    return () => clearTimeout(timer);
  }, [deadline]);
  return Number.isFinite(deadline) && deadline <= performance.now() ? null : verdict;
}

export function Px4ArmingBadge({ verdict: report }) {
  const verdict = useCurrentVerdict(report);
  const Icon = verdict?.can_arm ? FaCheckCircle : FaStopCircle;
  const label = verdict && `${verdict.label} · ${verdict.mode}`;
  return <span className="px4-arming-slot">
    {verdict && <span className={`px4-arming-badge is-${verdict.can_arm ? 'allowed' : 'blocked'}`}
      role="img" title={label} aria-label={label}><Icon aria-hidden="true" /></span>}
  </span>;
}

function RecheckPx4({ refresh }) {
  return <button type="button" className="operator-button operator-button--ghost px4-arming-recheck"
    aria-label="Recheck PX4 report" title="Recheck PX4 report" onClick={refresh}>
    <FaRedo aria-hidden="true" />
  </button>;
}

export function Px4ArmingDetails({ hwId, verdict: report, refresh }) {
  const verdict = useCurrentVerdict(report);
  const [details, setDetails] = useState(null);
  const revision = verdict?.revision;
  useEffect(() => {
    if (!revision || !hwId) return undefined;
    let active = true;
    const controller = new AbortController();
    fetchGcsResource(`/api/v1/fleet/aircraft/${encodeURIComponent(hwId)}/px4-arming-report`,
      { params: { revision }, signal: controller.signal }).then(({ data }) => {
      if (active && data.revision === revision) setDetails({ hwId, ...data });
    }).catch(() => {});
    return () => { active = false; controller.abort(); };
  }, [hwId, revision]);
  if (!verdict) return <span>PX4 report unavailable{refresh && <RecheckPx4 refresh={refresh} />}</span>;
  const reasons = details?.hwId === hwId && details.revision === revision ? details.mode_problems : null;
  return <div className="px4-arming-details">
    <p><Px4ArmingBadge verdict={verdict} />{verdict.label} · {verdict.mode}{refresh && <RecheckPx4 refresh={refresh} />}</p>
    {reasons?.length > 0 && <ul>{reasons.map((reason, index) => <li key={index}>
      {reason.description ? <details><summary>{reason.message}</summary><p>{reason.description}</p></details> : reason.message}
    </li>)}</ul>}
    {verdict.can_arm && <small>Arming permission for this mode.</small>}
  </div>;
}

export function Px4ArmingDisclosure({ hwId, verdict }) {
  const [open, setOpen] = useState(false);
  return <details className="px4-arming-disclosure" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary title="PX4 arming report" aria-label="PX4 arming report"><FaInfoCircle aria-hidden="true" /></summary>
    {open && <Px4ArmingDetails hwId={hwId} verdict={verdict} />}
  </details>;
}

export function Px4MissionIndicators({ ids, rows, now, refresh, takeoff = false }) {
  const [open, setOpen] = useState(false);
  if (!ids.length) return null;
  return <details className="px4-arming-disclosure" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary><FaInfoCircle aria-hidden="true" /> PX4 arming</summary>
    {open && refresh && <RecheckPx4 refresh={refresh} />}
    {open && [...new Set(ids.map(String).filter(Boolean))].map(id => {
      const verdict = px4ArmingVerdict(rows[id], now, takeoff);
      return <span className="px4-mission-indicator" key={id}><small>H{id}</small>
        <Px4ArmingBadge verdict={verdict} /><Px4ArmingDisclosure hwId={id} verdict={verdict} /></span>;
    })}
  </details>;
}
