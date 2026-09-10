import React, { useEffect, useState } from 'react';
import { FaNetworkWired } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import MissionCard from './MissionCard';

function makeKey() {
  return `dashboard-swarm-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function DashboardSmartSwarmStart() {
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [loading, setLoading] = useState(false);
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
  // Normal Dashboard start is intentionally one-click only for an
  // unambiguous saved formation. Multi-cluster layouts stay on the advanced
  // Swarm page where the operator can choose the cluster explicitly.
  const cluster = clusters.length === 1 ? clusters[0] : null;
  const unavailable = cluster?.partial_exclusion_hw_ids || [];
  const onlineCount = cluster?.members?.filter((m) => !unavailable.includes(m.hw_id)).length || 0;
  const start = async (partial = false) => {
    if (!cluster || loading) return;
    const excluded = partial ? unavailable : [];
    if (partial && !window.confirm(
      `Start only drones ${cluster.available_hw_ids.join(', ')}? Drones ${excluded.join(', ')} will be excluded. This is a partial formation.`,
    )) return;
    setLoading(true);
    try {
      await submitCommandWithLifecycleFeedback({
        mission_type: 2,
        trigger_time: 0,
        target_drone_ids: cluster.members
          .filter((member) => !excluded.includes(member.hw_id))
          .map((member) => member.hw_id),
        smart_swarm_start: {
          cluster_id: cluster.cluster_id,
          revision: preview.revision,
          excluded_hw_ids: excluded,
          idempotency_key: makeKey(),
        },
        uiMeta: { operatorLabel: partial ? 'Start partial Smart Swarm' : 'Start Smart Swarm' },
      }, commandLifecycleCallbacks);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : error?.message || 'Smart Swarm could not start');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mission-swarm-start">
      <MissionCard
        icon={<FaNetworkWired aria-hidden="true" />}
        category="Live formation"
        label={loading ? 'Starting Smart Swarm…' : 'Start Smart Swarm'}
        summary={previewError || (cluster
          ? `Leader ${cluster.cluster_id} · Drones ${cluster.members.map((m) => m.hw_id).join(', ')}`
          : clusters.length > 1
            ? `${clusters.length} formations — choose one in Smart Swarm Runtime.`
            : preview ? 'Save a formation in Swarm Design first.' : 'Loading saved formation…')}
        note="Start the saved formation after takeoff by MDS, QGC or RC. Uses these roles, not the dashboard checkboxes. Each aircraft checks its current flight state."
        disabled={loading || !cluster}
        onClick={() => start()}
      />
      {unavailable.length > 0 && (
        <small>No fresh telemetry: {unavailable.join(', ')}. Start still checks every aircraft.</small>
      )}
      {unavailable.length > 0 && onlineCount > 0 && (
        <button className="mission-swarm-partial" type="button" onClick={() => start(true)} disabled={loading}>
          Start without {unavailable.join(', ')}…
        </button>
      )}
    </div>
  );
}
