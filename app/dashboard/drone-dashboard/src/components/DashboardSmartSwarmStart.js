import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { FaPlay } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';

function makeKey() {
  return `dashboard-swarm-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function DashboardSmartSwarmStart({ drones = [] }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const { commandLifecycleCallbacks } = useCommandActivity();

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetchGcsResource('/api/v1/swarm/runtime/preview');
        if (live) setPreview(response.data);
      } catch (error) {
        if (live) setPreview(null);
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
  const start = async () => {
    if (!cluster || loading) return;
    const partial = unavailable.length > 0;
    if (partial && !window.confirm(
      `Drone ${unavailable.join(', ')} unavailable — start the reachable leader-only path?`,
    )) return;
    setLoading(true);
    try {
      await submitCommandWithLifecycleFeedback({
        mission_type: 2,
        trigger_time: 0,
        target_drone_ids: cluster.members
          .filter((member) => !unavailable.includes(member.hw_id))
          .map((member) => member.hw_id),
        smart_swarm_start: {
          cluster_id: cluster.cluster_id,
          revision: preview.revision,
          excluded_hw_ids: unavailable,
          idempotency_key: makeKey(),
        },
        uiMeta: { operatorLabel: partial ? 'Start partial Smart Swarm' : 'Start Smart Swarm' },
      }, commandLifecycleCallbacks);
    } catch (error) {
      toast.error(error?.response?.data?.detail || error?.message || 'Smart Swarm could not start');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="overview-smart-swarm-start" aria-label="Smart Swarm quick start">
      <div>
        <strong>Smart Swarm</strong>
        <span>
          {cluster
            ? `${cluster.members.length} saved roles · ${onlineCount} online · Leader ${cluster.cluster_id}`
            : clusters.length > 1
              ? `${clusters.length} saved formations · choose one on the Swarm page`
              : 'Loading saved formation…'}
        </span>
      </div>
      {cluster?.members?.length > 0 && (
        <button type="button" onClick={start} disabled={loading || onlineCount === 0} aria-label="Start Smart Swarm">
          <FaPlay /> {loading ? 'Starting…' : 'Start Swarm'}
        </button>
      )}
    </section>
  );
}

DashboardSmartSwarmStart.propTypes = { drones: PropTypes.array };
