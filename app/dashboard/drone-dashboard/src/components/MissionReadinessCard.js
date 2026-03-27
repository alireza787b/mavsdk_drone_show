import React, { useState, useEffect } from 'react';
import { getSwarmClusterStatus } from '../services/droneApiService';
import '../styles/MissionReadinessCard.css';

const MissionReadinessCard = ({ refreshTrigger = 0 }) => {
  const [clusterStatus, setClusterStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedClusters, setExpandedClusters] = useState(new Set());
  const [lightboxImage, setLightboxImage] = useState(null);

  useEffect(() => {
    fetchMissionReadiness();
  }, [refreshTrigger]);

  const fetchMissionReadiness = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSwarmClusterStatus();
      setClusterStatus(data);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Failed to fetch mission readiness:', err);
      setError('Failed to load mission status');
    } finally {
      setLoading(false);
    }
  };

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

    const totalClusters = clusterStatus.clusters.length;
    const readyClusters = clusterStatus.clusters.filter(c => c.has_trajectory).length;
    const percentage = totalClusters > 0 ? Math.round((readyClusters / totalClusters) * 100) : 0;

    if (percentage === 100) return { status: 'ready', percentage };
    if (percentage > 0) return { status: 'partial', percentage };
    return { status: 'not-ready', percentage };
  };

  const getClusterStatus = (cluster) => {
    if (cluster.has_trajectory) return 'ready';
    return 'missing';
  };

  const openLightbox = (imageSrc, title) => {
    setLightboxImage({ src: imageSrc, title });
  };

  const closeLightbox = () => {
    setLightboxImage(null);
  };

  const getDroneImagePath = (droneId) => {
    return `/static/plots/drone_${droneId}_trajectory.jpg`;
  };

  const getClusterImagePath = (leaderId) => {
    return `/static/plots/cluster_leader_${leaderId}.jpg`;
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
          <span className="loading-spinner">⏳</span>
          <span className="loading-text">Loading mission readiness...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mission-readiness-card error">
        <div className="error-content">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{error}</span>
          <button className="retry-btn" onClick={fetchMissionReadiness}>
            ↻ Retry
          </button>
        </div>
      </div>
    );
  }

  if (!clusterStatus?.clusters || clusterStatus.clusters.length === 0) {
    return (
      <div className="mission-readiness-card">
        <div className="empty-state">
          <span className="empty-icon">🤖</span>
          <div className="empty-text">
            <h4>No Clusters Found</h4>
            <p>Configure your swarm structure in the Swarm Trajectory page</p>
          </div>
          <a href="/swarm-trajectory" className="fix-link">
            Configure Swarm →
          </a>
        </div>
      </div>
    );
  }

  const overallStatus = getOverallStatus();
  const readyClusters = clusterStatus.clusters.filter(c => c.has_trajectory).length;
  const missingCount = clusterStatus.clusters.length - readyClusters;

  return (
    <div className="mission-readiness-card">
      {/* Header with overall status */}
      <div className="readiness-header">
        <div className="header-left">
          <h3>Swarm Mission Readiness</h3>
          <div className={`overall-status ${overallStatus.status}`}>
            {overallStatus.status === 'ready' ? '✅' :
             overallStatus.status === 'partial' ? '⚠️' : '❌'}
            {overallStatus.status === 'ready' ? 'Leader Coverage Ready' :
             overallStatus.status === 'partial' ? `${overallStatus.percentage}% Leaders Ready` :
             'Leader Coverage Missing'}
          </div>
        </div>

        <div className="header-right">
          <div className="quick-stats">
            <div className="stat">{clusterStatus.clusters.length} Clusters</div>
            <div className="stat">{readyClusters} leaders uploaded • {missingCount} missing</div>
          </div>
          <button
            className="refresh-btn"
            onClick={fetchMissionReadiness}
            title="Refresh status"
          >
            ↻
          </button>
        </div>
      </div>

      {/* Clusters grid with accordion */}
      <div className="clusters-grid">
        {clusterStatus.clusters.map((cluster, index) => {
          const clusterStatus = getClusterStatus(cluster);
          const isExpanded = expandedClusters.has(cluster.leader_id);

          return (
            <div key={cluster.leader_id} className={`cluster-card ${clusterStatus} ${isExpanded ? 'expanded' : ''}`}>
              {/* Cluster Header - Clickable */}
              <div
                className="cluster-header clickable"
                onClick={() => toggleCluster(cluster.leader_id)}
              >
                <div className="cluster-title">
                  <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                  <span>Leader {cluster.leader_id}</span>
                </div>

                <div className="header-actions">
                  <span className="csv-indicator">
                    {clusterStatus === 'ready' ? '✅' : '❌'}
                    {clusterStatus === 'ready' ? 'Ready' : 'Missing CSV'}
                  </span>
                  <button
                    className="preview-cluster-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      openLightbox(getClusterImagePath(cluster.leader_id), `Cluster ${cluster.leader_id} Formation`);
                    }}
                    title="Preview cluster formation"
                  >
                    👁️
                  </button>
                </div>
              </div>

              {/* Compact follower display */}
              <div className="drone-list">
                <div className="leader-drone">
                  <span className={`drone-id leader`}>[{cluster.leader_id}]</span>
                </div>
                <span className="followers-label">→</span>
                <div className="follower-drones">
                  <span className={`drone-id follower ${clusterStatus}`}>
                    {cluster.follower_count} follower{cluster.follower_count === 1 ? '' : 's'}
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
                          <span className={`drone-status ${clusterStatus}`}>
                            {clusterStatus === 'ready' ? '✅ Ready' : '❌ Missing CSV'}
                          </span>
                        </div>
                      </div>

                      <div className="drone-actions">
                        {clusterStatus === 'ready' && (
                          <button
                              className="preview-btn"
                              onClick={() => openLightbox(getDroneImagePath(cluster.leader_id), `Drone ${cluster.leader_id} Trajectory`)}
                              title="Preview trajectory"
                            >
                              📊 Leader preview
                            </button>
                          )}
                        </div>
                    </div>

                    {/* Followers */}
                    <div className="drone-detail-item follower-item">
                      <div className="drone-info">
                        <span className={`drone-id-large follower ${clusterStatus}`}>
                          {cluster.follower_count}
                        </span>
                        <div className="drone-meta">
                          <span className="drone-role">FOLLOWERS</span>
                          <span className={`drone-status ${clusterStatus}`}>
                            {clusterStatus === 'ready'
                              ? 'Topology linked to uploaded leader trajectory'
                              : 'Waiting for leader trajectory upload'}
                          </span>
                        </div>
                      </div>

                      <div className="drone-actions">
                        <span className="preview-btn preview-btn--note">
                          Individual follower verification is not exposed here yet.
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Action guidance */}
      {overallStatus.status !== 'ready' && (
        <div className="missing-warning">
          <span className="warning-icon">⚠️</span>
          <div className="warning-text">
            Action needed: {missingCount} leader trajectory{missingCount === 1 ? '' : 'ies'} missing
          </div>
          <a href="/swarm-trajectory" className="fix-link">
            Fix in Swarm Trajectory →
          </a>
        </div>
      )}

      {/* Professional Lightbox Modal */}
      {lightboxImage && (
        <div className="lightbox-overlay" onClick={closeLightbox}>
          <div className="lightbox-container" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-header">
              <h3>{lightboxImage.title}</h3>
              <button className="lightbox-close" onClick={closeLightbox}>
                ✕
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
