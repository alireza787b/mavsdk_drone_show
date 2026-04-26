import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  MdAssessment,
  MdCancel,
  MdCheckCircle,
  MdClose,
  MdExpandMore,
  MdHourglassEmpty,
  MdRefresh,
  MdSmartToy,
  MdVisibility,
  MdWarningAmber,
} from 'react-icons/md';
import useSwarmClusterStatus from '../hooks/useSwarmClusterStatus';
import { normalizeClusterState } from '../utilities/swarmTrajectoryViewModel';
import {
  formatSwarmTrajectoryAltitudeEnvelope,
  formatSwarmTrajectoryPackageTimingSummary,
} from '../utilities/swarmTrajectoryPackageStats';
import { buildStaticPlotUrl } from '../services/gcsApiService';
import '../styles/MissionReadinessCard.css';

const MissionReadinessCard = ({
  refreshTrigger = 0,
  clusterStatus: externalClusterStatus = null,
  loading: externalLoading = null,
  error: externalError = null,
  onRefresh = null,
}) => {
  const [expandedClusters, setExpandedClusters] = useState(new Set());
  const [lightboxImage, setLightboxImage] = useState(null);

  const hasExternalState = externalClusterStatus !== null || externalLoading !== null || externalError !== null;
  const {
    data: fetchedClusterStatus,
    loading: fetchedLoading,
    error: fetchedError,
    refresh: refreshClusterStatus,
  } = useSwarmClusterStatus({
    enabled: !hasExternalState,
    intervalMs: null,
    refreshTrigger,
  });

  const clusterStatus = hasExternalState ? externalClusterStatus : fetchedClusterStatus;
  const loading = hasExternalState ? Boolean(externalLoading) : fetchedLoading;
  const error = hasExternalState
    ? (typeof externalError === 'string' ? externalError : externalError?.message || null)
    : (fetchedError?.message || null);
  const handleRefresh = onRefresh || refreshClusterStatus;

  const toggleCluster = (clusterId) => {
    setExpandedClusters(prev => {
      const newSet = new Set(prev);
      if (newSet.has(clusterId)) {
        newSet.delete(clusterId);
      } else {
        newSet.add(clusterId);
      }
      return newSet;
    });
  };

  const getOverallStatus = () => {
    if (!clusterStatus?.clusters) return { status: 'unknown', percentage: 0 };

    const summary = clusterStatus.cluster_summary;
    const totalClusters = summary?.cluster_count ?? clusterStatus.clusters.length;
    const readyClusters = summary?.ready_cluster_count ?? clusterStatus.clusters.filter(c => c.ready).length;
    const percentage = totalClusters > 0 ? Math.round((readyClusters / totalClusters) * 100) : 0;

    if (summary?.overall_state === 'ready' || percentage === 100) return { status: 'ready', percentage };
    if (summary?.overall_state === 'partial' || percentage > 0) return { status: 'partial', percentage };
    if (summary?.overall_state === 'missing_uploads') return { status: 'missing', percentage };
    return { status: 'not-ready', percentage };
  };

  const getClusterStatus = (cluster) => {
    const state = normalizeClusterState(cluster.state);
    if (state === 'ready' || cluster.ready) return 'ready';
    if (state === 'partial_outputs') return 'processing';
    if (state === 'needs_processing' || cluster.leader_uploaded) return 'processing';
    return 'missing';
  };

  const getClusterStatusLabel = (cluster) => {
    switch (normalizeClusterState(cluster.state)) {
      case 'ready':
        return 'Ready';
      case 'partial_outputs':
        return 'Partial Outputs';
      case 'needs_processing':
        return 'Needs Processing';
      case 'missing_upload':
        return 'Missing CSV';
      default:
        return cluster.ready ? 'Ready' : cluster.leader_uploaded ? 'Needs Processing' : 'Missing CSV';
    }
  };

  const renderStatusIcon = (tone, className = 'readiness-status-icon') => {
    const Icon = tone === 'ready'
      ? MdCheckCircle
      : tone === 'processing'
        ? MdHourglassEmpty
        : MdCancel;
    return <Icon className={`${className} ${tone}`} aria-hidden="true" />;
  };

  const openLightbox = (imageSrc, title) => {
    setLightboxImage({ src: imageSrc, title });
  };

  const closeLightbox = () => {
    setLightboxImage(null);
  };

  const getDroneImagePath = (droneId) => {
    return buildStaticPlotUrl(`drone_${droneId}_trajectory.jpg`);
  };

  const getClusterImagePath = (leaderId) => {
    return buildStaticPlotUrl(`cluster_leader_${leaderId}.jpg`);
  };

  // Handle ESC key for lightbox
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && lightboxImage) {
        closeLightbox();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [lightboxImage]);

  if (loading) {
    return (
      <div className="mission-readiness-card loading">
        <div className="loading-content">
          <MdHourglassEmpty className="loading-spinner" aria-hidden="true" />
          <span className="loading-text">Loading mission readiness...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mission-readiness-card error">
        <div className="error-content">
          <MdWarningAmber className="error-icon" aria-hidden="true" />
          <span className="error-text">{error}</span>
        </div>
      </div>
    );
  }

  if (!clusterStatus?.clusters || clusterStatus.clusters.length === 0) {
    return (
      <div className="mission-readiness-card">
        <div className="empty-state">
          <MdSmartToy className="empty-icon" aria-hidden="true" />
          <div className="empty-text">
            <h4>No Clusters Found</h4>
            <p>Configure the swarm in Swarm Design, then send leader paths from Trajectory Planning or upload them in Swarm Trajectory.</p>
          </div>
          <Link to="/swarm-design" className="fix-link">
            Configure Swarm →
          </Link>
        </div>
      </div>
    );
  }

  const overallStatus = getOverallStatus();
  const summary = clusterStatus.cluster_summary || {};
  const session = clusterStatus.session || {};
  const readyClusters = summary.ready_cluster_count ?? clusterStatus.clusters.filter(c => c.ready).length;
  const processingCount = (summary.needs_processing_cluster_count ?? 0) + (summary.partial_output_cluster_count ?? 0);
  const missingCount = summary.missing_upload_cluster_count ?? clusterStatus.clusters.filter(c => !c.leader_uploaded).length;
  const totalClusters = summary.cluster_count ?? clusterStatus.clusters.length;
  const processedDroneCount = clusterStatus.processed_drones?.length ?? 0;
  const expectedDroneCount = session.total_drones
    || clusterStatus.clusters.reduce(
      (count, cluster) => count + (cluster.expected_drone_count ?? ((cluster.follower_count || 0) + 1)),
      0,
    );
  const packageStats = clusterStatus.package_stats || {};
  const actionItems = [];

  if (missingCount > 0) {
    actionItems.push({
      tone: 'danger',
      text: `${missingCount} top-leader upload${missingCount === 1 ? '' : 's'} are still missing.`,
    });
  }

  if (processingCount > 0) {
    actionItems.push({
      tone: 'warning',
      text: `${processingCount} cluster${processingCount === 1 ? ' still needs' : 's still need'} follower regeneration or output review.`,
    });
  }

  if (missingCount === 0 && processingCount === 0 && readyClusters === totalClusters && processedDroneCount > 0) {
    actionItems.push({
      tone: 'success',
      text: `Mission package is ready for launch preflight with ${processedDroneCount} processed drone output${processedDroneCount === 1 ? '' : 's'}.`,
    });
  }

  const actionLinks = [
    { label: 'Swarm Design', to: '/swarm-design' },
    { label: 'Trajectory Planning', to: '/trajectory-planning' },
    { label: 'Swarm Trajectory', to: '/swarm-trajectory' },
  ];

  return (
    <div className="mission-readiness-card">
      {/* Header with overall status */}
      <div className="readiness-header">
        <div className="header-left">
          <h3>Swarm Mission Readiness</h3>
          <div className={`overall-status ${overallStatus.status}`}>
            {overallStatus.status === 'ready' ? 'Mission Trajectories Ready' :
             overallStatus.status === 'partial' ? `${overallStatus.percentage}% Clusters Ready` :
             'Mission Trajectories Incomplete'}
          </div>
        </div>

        <div className="header-right">
          <div className="quick-stats">
            <div className="stat">{clusterStatus.clusters.length} Clusters</div>
            <div className="stat">
              {readyClusters} ready • {processingCount} pending process • {missingCount} missing upload
            </div>
          </div>
          <button
            className="refresh-btn"
            onClick={handleRefresh}
            title="Refresh status"
            aria-label="Refresh mission readiness"
          >
            <MdRefresh aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="readiness-summary-grid">
        <div className="readiness-summary-tile">
          <span className="readiness-summary-tile__label">Ready Clusters</span>
          <strong className="readiness-summary-tile__value">{readyClusters}/{totalClusters}</strong>
        </div>
        <div className="readiness-summary-tile">
          <span className="readiness-summary-tile__label">Processed Drones</span>
          <strong className="readiness-summary-tile__value">{processedDroneCount}/{expectedDroneCount || processedDroneCount}</strong>
        </div>
        <div className="readiness-summary-tile">
          <span className="readiness-summary-tile__label">Missing Uploads</span>
          <strong className="readiness-summary-tile__value">{missingCount}</strong>
        </div>
        <div className="readiness-summary-tile">
          <span className="readiness-summary-tile__label">Active Session</span>
          <strong className="readiness-summary-tile__value">{session.exists ? session.session_id : 'None'}</strong>
        </div>
      </div>

      {session.exists ? (
        <div className="readiness-session-note">
          Current processed package: <strong>{session.session_id}</strong> • leaders {session.processed_leaders?.length || 0} • drones {session.total_drones || processedDroneCount}
        </div>
      ) : null}

      {packageStats?.available ? (
        <>
          <div className="readiness-session-note">
            Package timing: <strong>{formatSwarmTrajectoryPackageTimingSummary(packageStats)}</strong>
          </div>
          {formatSwarmTrajectoryAltitudeEnvelope(packageStats) !== 'Unknown' ? (
            <div className="readiness-session-note">
              Altitude envelope: <strong>{formatSwarmTrajectoryAltitudeEnvelope(packageStats)}</strong>
            </div>
          ) : null}
        </>
      ) : null}

      {actionItems.length > 0 ? (
        <div className="readiness-action-items">
          {actionItems.map((item) => (
            <div key={item.text} className={`readiness-action-item readiness-action-item--${item.tone}`}>
              {item.text}
            </div>
          ))}
        </div>
      ) : null}

      <div className="readiness-quick-links">
        {actionLinks.map((link) => (
          <Link key={link.to} to={link.to} className="readiness-quick-link">
            {link.label}
          </Link>
        ))}
      </div>

      {/* Clusters grid with accordion */}
      <div className="clusters-grid">
        {clusterStatus.clusters.map((cluster, index) => {
          const clusterTone = getClusterStatus(cluster);
          const isExpanded = expandedClusters.has(cluster.leader_id);

          return (
            <div key={cluster.leader_id} className={`cluster-card ${clusterTone} ${isExpanded ? 'expanded' : ''}`}>
              {/* Cluster Header - Clickable */}
              <div
                className="cluster-header clickable"
                onClick={() => toggleCluster(cluster.leader_id)}
              >
                <div className="cluster-title">
                  <MdExpandMore
                    className={`expand-icon ${isExpanded ? 'expanded' : ''}`}
                    aria-hidden="true"
                  />
                  <span>Leader {cluster.leader_id}</span>
                </div>

                <div className="header-actions">
                  <span className="csv-indicator">
                    {renderStatusIcon(clusterTone)}
                    <span>{getClusterStatusLabel(cluster)}</span>
                  </span>
                  {cluster.cluster_plot_available && (
                    <button
                      className="preview-cluster-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        openLightbox(getClusterImagePath(cluster.leader_id), `Cluster ${cluster.leader_id} Formation`);
                      }}
                      title="Preview cluster formation"
                      aria-label={`Preview cluster ${cluster.leader_id} formation`}
                    >
                      <MdVisibility aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>

              {/* Compact follower display */}
                <div className="drone-list">
                  <div className="leader-drone">
                    <span className={`drone-id leader`}>[{cluster.leader_id}]</span>
                  </div>
                <span className="followers-label">→</span>
                <div className="follower-drones">
                  <span className={`drone-id follower ${clusterTone}`}>
                    {cluster.processed_drone_count ?? 0}/{cluster.expected_drone_count ?? (cluster.follower_count + 1)} ready
                  </span>
                </div>
              </div>

              {/* Accordion Details */}
              {isExpanded && (
                <div className="cluster-details">
                  <div className="details-header">
                    <h4>Cluster Details</h4>
                    <span className="drone-count">{cluster.follower_count + 1} drones</span>
                  </div>

                  <div className="drone-details-list">
                    {/* Leader */}
                    <div className="drone-detail-item leader-item">
                      <div className="drone-info">
                        <span className={`drone-id-large leader`}>[{cluster.leader_id}]</span>
                        <div className="drone-meta">
                          <span className="drone-role">LEADER</span>
                          <span className={`drone-status ${clusterTone}`}>
                            {renderStatusIcon(clusterTone)}
                            <span>
                              {clusterTone === 'ready'
                                ? 'Ready'
                                : normalizeClusterState(cluster.state) === 'partial_outputs'
                                  ? 'Cluster outputs incomplete'
                                  : clusterTone === 'processing'
                                    ? 'Uploaded, processing required'
                                    : 'Missing CSV'}
                            </span>
                          </span>
                        </div>
                      </div>

                      <div className="drone-actions">
                        {cluster.leader_plot_available && (
                          <button
                              className="preview-btn"
                              onClick={() => openLightbox(getDroneImagePath(cluster.leader_id), `Drone ${cluster.leader_id} Trajectory`)}
                              title="Preview trajectory"
                            >
                              <MdAssessment aria-hidden="true" />
                              Leader preview
                            </button>
                          )}
                        </div>
                    </div>

                    {/* Followers */}
                    <div className="drone-detail-item follower-item">
                      <div className="drone-info">
                        <span className={`drone-id-large follower ${clusterTone}`}>
                          {cluster.follower_count}
                        </span>
                        <div className="drone-meta">
                          <span className="drone-role">FOLLOWERS</span>
                          <span className={`drone-status ${clusterTone}`}>
                            {clusterTone === 'ready'
                              ? 'Follower outputs are processed and ready.'
                              : normalizeClusterState(cluster.state) === 'partial_outputs'
                                ? `${cluster.processed_follower_ids?.length || 0} processed • ${(cluster.missing_follower_ids || []).length} missing`
                                : clusterTone === 'processing'
                                  ? 'Follower paths will appear after processing.'
                                  : 'Waiting for leader trajectory upload.'}
                          </span>
                        </div>
                      </div>

                      <div className="drone-actions">
                        <span className="preview-btn preview-btn--note">
                          {cluster.follower_ids?.length > 0
                            ? `Follower IDs: ${cluster.follower_ids.join(', ')}`
                            : 'No followers assigned to this leader.'}
                        </span>
                        {(cluster.missing_follower_ids || []).length > 0 ? (
                          <span className="preview-btn preview-btn--note">
                            Missing outputs: {cluster.missing_follower_ids.join(', ')}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  {(cluster.issues?.length || cluster.advisories?.length) ? (
                    <div className="drone-actions">
                      {(cluster.issues || []).map((issue) => (
                        <span key={issue} className="preview-btn preview-btn--note">
                          Issue: {issue}
                        </span>
                      ))}
                      {(cluster.advisories || []).map((advisory) => (
                        <span key={advisory} className="preview-btn preview-btn--note">
                          Advisory: {advisory}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Action guidance */}
      {overallStatus.status !== 'ready' && (
        <div className="missing-warning">
          <MdWarningAmber className="warning-icon" aria-hidden="true" />
          <div className="warning-text">
            Action needed:{' '}
            {missingCount > 0 && processingCount > 0
              ? `${missingCount} leader upload${missingCount === 1 ? '' : 's'} missing • ${processingCount} uploaded cluster${processingCount === 1 ? '' : 's'} still need processing`
              : missingCount > 0
                ? `${missingCount} leader trajectory upload${missingCount === 1 ? '' : 's'} missing`
                : `${processingCount} uploaded cluster${processingCount === 1 ? '' : 's'} still need processing`}
          </div>
          <Link to="/swarm-trajectory" className="fix-link">
            Fix in Swarm Trajectory →
          </Link>
        </div>
      )}

      {/* Professional Lightbox Modal */}
      {lightboxImage && (
        <div className="lightbox-overlay" onClick={closeLightbox}>
          <div className="lightbox-container" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-header">
              <h3>{lightboxImage.title}</h3>
              <button className="lightbox-close" onClick={closeLightbox} aria-label="Close trajectory preview">
                <MdClose aria-hidden="true" />
              </button>
            </div>
            <div className="lightbox-content">
              <img
                src={lightboxImage.src}
                alt={lightboxImage.title}
                className="lightbox-image"
                onError={(e) => {
                  e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="100%" height="100%" fill="%23f8fafc"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="%23667eea" text-anchor="middle">Trajectory Plot</text></svg>';
                }}
              />
            </div>
            <div className="lightbox-footer">
              <span className="lightbox-hint">Click outside or press ESC to close</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MissionReadinessCard;
