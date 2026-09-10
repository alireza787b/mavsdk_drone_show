import React, { useEffect, useRef, useState } from 'react';
import { FaNetworkWired } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import MissionCard from './MissionCard';
import { ConfirmDialog } from './ui/OperatorPrimitives';

function makeKey() {
  return `dashboard-swarm-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function movementSummary(member) {
  if (String(member.follow) === '0') return 'Leader · stays under your control';
  const body = member.frame === 'body';
  const x = Number(member.offset_x || 0);
  const y = Number(member.offset_y || 0);
  const z = Number(member.offset_z || 0);
  const offsets = [
    x && `${Math.abs(x)} m ${body ? (x > 0 ? 'ahead' : 'behind') : (x > 0 ? 'north' : 'south')}`,
    y && `${Math.abs(y)} m ${body ? (y > 0 ? 'right' : 'left') : (y > 0 ? 'east' : 'west')}`,
    z ? `${Math.abs(z)} m ${z > 0 ? 'above' : 'below'}` : 'same height',
  ].filter(Boolean).join(' · ');
  return `Follow Drone ${member.follow} · ${offsets}`;
}

function memberStatus(member) {
  if (!member.available) return 'No recent telemetry';
  if (member.armed === false) return 'Disarmed';
  if (member.armed === true) return 'Armed';
  return 'Flight state unknown';
}

export default function DashboardSmartSwarmStart({ review = false, onReview, onBack }) {
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const inFlight = useRef(false);
  const { commandLifecycleCallbacks } = useCommandActivity();

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetchGcsResource('/api/v1/swarm/runtime/preview');
        if (live) {
          setPreview(response.data);
          setPreviewError(null);
        }
      } catch (error) {
        if (live) {
          setPreview(null);
          setPreviewError('Formation unavailable; retrying…');
        }
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => { live = false; clearInterval(timer); };
  }, []);

  const clusters = Array.isArray(preview?.clusters) ? preview.clusters : [];
  // Opening the card never dispatches. Review -> Start -> Confirm is shared
  // with the other operator mission flows, without a second flight policy.
  const cluster = clusters.length === 1 ? clusters[0] : null;
  const unavailable = cluster?.partial_exclusion_hw_ids || [];
  const onlineCount = cluster?.members?.filter((m) => !unavailable.includes(m.hw_id)).length || 0;
  const requestConfirmation = (partial = false) => {
    if (!cluster || loading || previewError) return;
    const excluded = partial ? unavailable : [];
    setConfirmation({ cluster, revision: preview.revision, excluded, key: makeKey() });
  };
  const start = async () => {
    if (!confirmation || inFlight.current) return;
    if (previewError || confirmation.revision !== preview?.revision) {
      setConfirmation(null);
      toast.warn('Formation changed or unavailable. Review it before starting.');
      return;
    }
    const { cluster: confirmedCluster, revision, excluded, key } = confirmation;
    const partial = excluded.length > 0;
    inFlight.current = true;
    setLoading(true);
    setConfirmation(null);
    try {
      await submitCommandWithLifecycleFeedback({
        mission_type: 2,
        trigger_time: 0,
        target_drone_ids: confirmedCluster.members
          .filter((member) => !excluded.includes(member.hw_id))
          .map((member) => member.hw_id),
        smart_swarm_start: {
          cluster_id: confirmedCluster.cluster_id,
          revision,
          excluded_hw_ids: excluded,
          idempotency_key: key,
        },
        uiMeta: { operatorLabel: partial ? 'Start partial Smart Swarm' : 'Start Smart Swarm' },
      }, commandLifecycleCallbacks);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : error?.message || 'Smart Swarm could not start');
    } finally {
      setLoading(false);
      inFlight.current = false;
    }
  };

  if (!review) return (
      <MissionCard
        icon={<FaNetworkWired aria-hidden="true" />}
        category="Live formation"
        label="Smart Swarm"
        summary={previewError || (cluster
          ? `Leader ${cluster.cluster_id} · Drones ${cluster.members.map((m) => m.hw_id).join(', ')}`
          : clusters.length > 1
            ? `${clusters.length} formations — choose one in Smart Swarm Runtime.`
            : preview ? 'Save a formation in Swarm Design first.' : 'Loading saved formation…')}
        note="Review the formation before starting. Clicking this card sends no command."
        onClick={onReview}
      />
  );

  return (
    <section className="mission-swarm-review" aria-label="Smart Swarm review">
      <header>
        <h3>Smart Swarm</h3>
        <span>{cluster ? `${cluster.members.length} drones · saved formation` : 'Formation review'}</span>
      </header>
      {previewError && <p role="status">{previewError}</p>}
      {!preview && !previewError && <p role="status">Loading saved formation…</p>}
      {preview && !cluster && (
        <p><a href="/swarm-design">{clusters.length > 1 ? 'Choose a formation in Swarm Design' : 'Save a formation in Swarm Design'}</a></p>
      )}
      {cluster && (
        <ul className="mission-swarm-review__roles">
          {cluster.members.map((member) => (
            <li key={member.hw_id}>
              <strong>Drone {member.hw_id}</strong>
              <span>{movementSummary(member)}</span>
              <small>{memberStatus(member)}</small>
            </li>
          ))}
        </ul>
      )}
      <p className="mission-swarm-review__hint">Use after takeoff. This starts following; it does not arm or take off.</p>
      {unavailable.length > 0 && (
        <small>No recent telemetry: Drone {unavailable.join(', ')}. Each aircraft checks its flight state at start.</small>
      )}
      <footer>
        <button type="button" className="operator-button operator-button--ghost" onClick={onBack} disabled={loading}>Back</button>
        {unavailable.length > 0 && onlineCount > 0 && (
          <button className="mission-swarm-partial" type="button" onClick={() => requestConfirmation(true)} disabled={loading}>
            Start without {unavailable.join(', ')}…
          </button>
        )}
        <button type="button" className="operator-button operator-button--primary" onClick={() => requestConfirmation()} disabled={loading || !cluster || Boolean(previewError)}>
          {loading ? 'Sending…' : 'Start Smart Swarm'}
        </button>
      </footer>
      <ConfirmDialog
        open={Boolean(confirmation)}
        title="Start Smart Swarm now?"
        message={confirmation ? (
          <div>
            <p>Drones {confirmation.cluster.members.filter((m) => !confirmation.excluded.includes(m.hw_id)).map((m) => m.hw_id).join(', ')} · Leader {confirmation.cluster.cluster_id}</p>
            {confirmation.cluster.members.filter((m) => String(m.follow) !== '0' && !confirmation.excluded.includes(m.hw_id)).map((m) => (
              <p key={m.hw_id}>Drone {m.hw_id}: {movementSummary(m)}</p>
            ))}
            {confirmation.excluded.length > 0 && <p>Partial formation · excludes Drone {confirmation.excluded.join(', ')}.</p>}
          </div>
        ) : ''}
        confirmLabel="Confirm start"
        cancelLabel="Back"
        busy={loading}
        onConfirm={start}
        onCancel={() => setConfirmation(null)}
      />
    </section>
  );
}
