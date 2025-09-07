import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
import '../styles/SwarmTrajectory.css';

const SwarmTrajectory = () => {
  const [leaders, setLeaders] = useState([]);
  const [hierarchies, setHierarchies] = useState({});
  const [followerDetails, setFollowerDetails] = useState({});
  const [uploadedLeaders, setUploadedLeaders] = useState(new Set());
  const [processing, setProcessing] = useState(false);
  const [results, setResults] = useState(null);
  const [status, setStatus] = useState(null);
  const [simulationMode, setSimulationMode] = useState(false);
  const [lightboxImage, setLightboxImage] = useState(null);
  const [committing, setCommitting] = useState(false);
  const [commitProgress, setCommitProgress] = useState(null);

  useEffect(() => {
    fetchLeaders();
    fetchStatus();
  }, []);

  const fetchLeaders = async () => {
    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/leaders`);
      const data = await response.json();
      
      if (data.success) {
        setLeaders(data.leaders);
        setHierarchies(data.hierarchies);
        setFollowerDetails(data.follower_details || {});
        setUploadedLeaders(new Set(data.uploaded_leaders));
        setSimulationMode(data.simulation_mode);
      } else {
        console.error('Failed to fetch leaders:', data.error);
        alert(`Failed to load swarm configuration: ${data.error}`);
      }
    } catch (error) {
      console.error('Error fetching leaders:', error);
      alert('Error connecting to backend. Please check server status.');
    }
  };

  const fetchStatus = async () => {
    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/status`);
      const data = await response.json();
      
      if (data.success) {
        setStatus(data.status);
      }
    } catch (error) {
      console.error('Error fetching status:', error);
    }
  };

  const handleFileUpload = async (leaderId, file) => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/upload/${leaderId}`, {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        setUploadedLeaders(prev => new Set([...prev, leaderId]));
        await fetchStatus(); // Refresh status
        alert(`Drone ${leaderId} trajectory uploaded successfully`);
      } else {
        alert(`Upload failed: ${result.error}`);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert(`Upload error: ${error.message}`);
    }
  };

  const processTrajectories = async () => {
    if (uploadedLeaders.size === 0) {
      alert('Please upload at least one drone trajectory before processing.');
      return;
    }

    setProcessing(true);
    setResults(null);

    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/process`, {
        method: 'POST'
      });
      const result = await response.json();
      
      setResults(result);
      await fetchStatus(); // Refresh status
      
      if (result.success) {
        alert(`Processing complete! ${result.processed_drones} drones processed successfully.`);
      } else {
        alert(`Processing failed: ${result.error}`);
      }
    } catch (error) {
      console.error('Processing error:', error);
      alert(`Processing error: ${error.message}`);
    } finally {
      setProcessing(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm('This will clear all uploaded trajectories, processed files, and generated plots. Continue?')) {
      return;
    }

    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/clear`, {
        method: 'POST'
      });
      const result = await response.json();
      
      if (result.success) {
        setUploadedLeaders(new Set());
        setResults(null);
        await fetchStatus(); // Refresh status
        alert('All trajectory files cleared successfully');
      } else {
        alert(`Clear failed: ${result.error}`);
      }
    } catch (error) {
      console.error('Clear error:', error);
      alert(`Clear error: ${error.message}`);
    }
  };

  const downloadDroneTrajectory = async (droneId) => {
    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/download/${droneId}`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Drone ${droneId}_trajectory.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      } else {
        const error = await response.json();
        alert(`Download failed: ${error.error}`);
      }
    } catch (error) {
      console.error('Download error:', error);
      alert(`Download error: ${error.message}`);
    }
  };

  const downloadDroneKML = async (droneId) => {
    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/download-kml/${droneId}`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Drone ${droneId}_trajectory.kml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        alert(`KML file downloaded! Open with Google Earth to view 3D trajectory over terrain.`);
      } else {
        const error = await response.json();
        alert(`KML download failed: ${error.error}`);
      }
    } catch (error) {
      console.error('KML download error:', error);
      alert(`KML download error: ${error.message}`);
    }
  };

  const getFollowersForLeader = (leaderId) => {
    return followerDetails[leaderId] || [];
  };

  const clearSingleTrajectory = async (leaderId) => {
    if (!window.confirm(`Clear trajectory for Drone ${leaderId}? This will also remove all associated follower trajectories.`)) {
      return;
    }

    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/clear-leader/${leaderId}`, {
        method: 'POST'
      });

      if (response.ok) {
        // Remove from uploaded leaders
        setUploadedLeaders(prev => {
          const newSet = new Set(prev);
          newSet.delete(leaderId);
          return newSet;
        });
        
        // Clear results if no leaders left
        if (uploadedLeaders.size === 1) {
          setResults(null);
        }
        
        await fetchStatus(); // Refresh status
        alert(`Drone ${leaderId} trajectory cleared successfully`);
      } else {
        const error = await response.json();
        alert(`Clear failed: ${error.error}`);
      }
    } catch (error) {
      console.error('Clear single trajectory error:', error);
      alert(`Clear error: ${error.message}`);
    }
  };

  const clearIndividualDrone = async (droneId) => {
    if (!window.confirm(`🗑️ Remove trajectory for Drone ${droneId}?\n\nThis will delete the drone's trajectory file and plot. This action cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/clear-drone/${droneId}`, {
        method: 'POST'
      });

      if (response.ok) {
        await fetchStatus(); // Refresh status
        alert(`✅ Drone ${droneId} trajectory removed successfully`);
      } else {
        const error = await response.json();
        alert(`❌ Delete failed: ${error.error}`);
      }
    } catch (error) {
      console.error('Delete drone error:', error);
      alert(`❌ Delete error: ${error.message}`);
    }
  };

  const openLightbox = (imageSrc, title) => {
    setLightboxImage({ src: imageSrc, title });
  };

  const closeLightbox = () => {
    setLightboxImage(null);
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

  const commitAndPushChanges = async () => {
    if (!results || results.processed_drones === 0) {
      alert('⚠️ No trajectories to commit. Please process trajectories first.');
      return;
    }

    const confirmed = window.confirm(`🚀 Commit & Push Trajectory Changes?\n\nThis will:\n✅ Save all processed trajectories to git\n✅ Push to remote repository\n✅ Make trajectories available to all drones\n\nProcessed drones: ${results.processed_drones}\nContinue?`);
    
    if (!confirmed) return;

    setCommitting(true);
    setCommitProgress({ step: 'Preparing...', progress: 10 });

    try {
      // Simulate progress steps for better UX
      const progressSteps = [
        { step: 'Staging trajectory files...', progress: 25 },
        { step: 'Creating git commit...', progress: 50 },
        { step: 'Pushing to remote repository...', progress: 75 },
        { step: 'Finalizing...', progress: 90 }
      ];

      for (const progressStep of progressSteps) {
        setCommitProgress(progressStep);
        await new Promise(resolve => setTimeout(resolve, 800)); // Smooth progress
      }

      const response = await fetch(`${getBackendURL()}/api/swarm/trajectory/commit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: `Swarm trajectory update: ${results.processed_drones} drones processed - ${new Date().toISOString().split('T')[0]}`
        })
      });

      const data = await response.json();

      if (data.success) {
        setCommitProgress({ step: 'Success!', progress: 100 });
        
        setTimeout(() => {
          alert(`✅ Trajectory changes committed successfully!\n\n📊 ${results.processed_drones} drone trajectories pushed to repository\n🌐 All drones now have access to the latest trajectories\n\n${data.git_info?.message || 'Git operations completed successfully'}`);
          setCommitProgress(null);
        }, 500);
      } else {
        throw new Error(data.error || 'Commit failed');
      }

    } catch (error) {
      console.error('Commit error:', error);
      setCommitProgress(null);
      alert(`❌ Commit failed: ${error.message}\n\nPlease check your git configuration and try again.`);
    } finally {
      setCommitting(false);
    }
  };

  return (
    <div className="swarm-trajectory">
      {/* Header with clear title and mode indicator */}
      <div className="header">
        <div className="title-section">
          <h1>Swarm Trajectory Planning</h1>
          <p className="subtitle">Upload drone trajectories and process swarm formations automatically</p>
        </div>
        <div className="mode-badge">
          {simulationMode ? 'SIMULATION' : 'LIVE'}
        </div>
      </div>

      {/* Clean Workflow Guidance */}
      <div className="workflow-guide">
        <div className="guide-content">
          <span className="guide-icon">💡</span>
          <div className="guide-text">
            <span className="guide-main">Complete Workflow:</span>
            <span className="guide-steps">
              1. <a href="/swarm-design" className="guide-link">Design your swarm structure</a>
              {' → '}
              2. <a href="/trajectory-planning" className="guide-link">Plan trajectories</a>
              {' → '}
              3. Upload exported CSV files here to generate swarm trajectories
            </span>
          </div>
        </div>
      </div>

      {/* Current Status - Clean overview */}
      <div className="status-card">
        <h2>Current Status</h2>
        <div className="status-metrics">
          <div className="metric">
            <span className="metric-value">{leaders.length}</span>
            <span className="metric-label">Clusters Found</span>
          </div>
          <div className="metric">
            <span className="metric-value">{uploadedLeaders.size}</span>
            <span className="metric-label">Uploaded</span>
          </div>
          <div className="metric">
            <span className="metric-value">{status?.processed_trajectories || 0}</span>
            <span className="metric-label">Processed</span>
          </div>
        </div>
      </div>

      {/* Step-by-step workflow */}
      {leaders.length > 0 ? (
        <>
          {/* Step 1: Upload Trajectories */}
          <div className="workflow-step">
            <div className="step-header">
              <h3><span className="step-number">1</span>Upload Drone Trajectories</h3>
              <p>Upload CSV files for each lead drone. Followers will be calculated automatically.</p>
            </div>
            
            <div className="leaders-grid">
              {leaders.map(leaderId => (
                <div key={leaderId} className={`leader-card ${uploadedLeaders.has(leaderId) ? 'completed' : 'pending'}`}>
                  <div className="leader-header">
                    <h4>Drone {leaderId}</h4>
                    <span className="follower-badge">
                      {hierarchies[leaderId] || 0} followers
                    </span>
                  </div>
                  
                  <div className="upload-area">
                    <input
                      type="file"
                      accept=".csv"
                      onChange={(e) => {
                        if (e.target.files[0]) {
                          handleFileUpload(leaderId, e.target.files[0]);
                        }
                      }}
                      id={`file-${leaderId}`}
                      style={{ display: 'none' }}
                    />
                    <label htmlFor={`file-${leaderId}`} className="upload-btn">
                      {uploadedLeaders.has(leaderId) ? (
                        <>
                          <span className="upload-icon">✓</span>
                          Replace CSV
                        </>
                      ) : (
                        <>
                          <span className="upload-icon">↑</span>
                          Upload CSV
                        </>
                      )}
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Step 2: Process Formation */}
          <div className="workflow-step">
            <div className="step-header">
              <h3><span className="step-number">2</span>Process Formation</h3>
              <p>Generate smooth trajectories for all drones with follower positions calculated automatically.</p>
            </div>
            
            <div className="process-controls">
              <button 
                className={`process-btn ${processing ? 'processing' : ''} ${uploadedLeaders.size === 0 ? 'disabled' : ''}`}
                onClick={processTrajectories} 
                disabled={processing || uploadedLeaders.size === 0}
              >
                {processing ? (
                  <>
                    <span className="spinner"></span>
                    Processing Formation...
                  </>
                ) : (
                  <>
                    <span className="process-icon">⚡</span>
                    Process Swarm Formation
                  </>
                )}
              </button>
              
              {uploadedLeaders.size === 0 && (
                <p className="requirement-note">Please upload at least one drone trajectory</p>
              )}
            </div>
          </div>

          {/* Step 3: Results & Download */}
          {results && (
            <div className="workflow-step">
              <div className="step-header">
                <h3><span className="step-number">3</span>Results & Download</h3>
              </div>
              
              {results.success ? (
                <div className="success-card">
                  <div className="success-header">
                    <span className="success-icon">✅</span>
                    <div>
                      <h4>Processing Complete!</h4>
                      <p>{results.processed_drones} drones processed successfully</p>
                    </div>
                  </div>
                  
                  {results.statistics && (
                    <div className="processing-stats">
                      <div className="stat">
                        <span className="stat-value">{results.statistics.leaders}</span>
                        <span className="stat-label">Lead Drones</span>
                      </div>
                      <div className="stat">
                        <span className="stat-value">{results.statistics.followers}</span>
                        <span className="stat-label">Followers</span>
                      </div>
                      {results.statistics.errors > 0 && (
                        <div className="stat error">
                          <span className="stat-value">{results.statistics.errors}</span>
                          <span className="stat-label">Errors</span>
                        </div>
                      )}
                    </div>
                  )}
                  
                  <div className="next-steps">
                    <p><strong>Next:</strong> Set Mission Type 4 (Swarm Trajectory) and trigger the mission</p>
                  </div>
                  
                  {/* Advanced Preview Section - Progressive Disclosure */}
                  <div className="advanced-section">
                    <details className="trajectory-preview">
                      <summary className="preview-toggle">
                        <span className="toggle-icon">📊</span>
                        View Trajectory Previews & Advanced Controls
                        <span className="toggle-hint">Click to expand</span>
                      </summary>
                      
                      <div className="preview-content">
                        {/* Cluster-based organization */}
                        {leaders.filter(leaderId => uploadedLeaders.has(leaderId)).map(leaderId => (
                          <div key={leaderId} className="cluster-section">
                            <div className="cluster-header">
                              <h4>🎯 Cluster {leaderId} Formation</h4>
                              <span className="cluster-stats">
                                {1 + (hierarchies[leaderId] || 0)} drones total
                              </span>
                            </div>
                            
                            {/* Cluster Overview Plot */}
                            <div className="cluster-plot-section">
                              <div className="cluster-plot-card">
                                <div className="cluster-plot-header">
                                  <h5>📊 Complete Cluster View</h5>
                                  <span className="plot-description">All trajectories in this formation</span>
                                </div>
                                <div className="cluster-plot clickable" onClick={() => openLightbox(`${getBackendURL()}/static/plots/cluster_leader_${leaderId}.jpg`, `Cluster ${leaderId} Formation`)}>
                                  <img 
                                    src={`${getBackendURL()}/static/plots/cluster_leader_${leaderId}.jpg`}
                                    alt={`Cluster ${leaderId} formation trajectories`}
                                    onError={(e) => {
                                      e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="100%" height="100%" fill="%23f8fafc"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="%23667eea" text-anchor="middle">Cluster Formation Plot</text></svg>';
                                    }}
                                  />
                                  <div className="zoom-overlay">
                                    <span className="zoom-icon">🔍</span>
                                    <span>Click to enlarge</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                            
                            {/* Individual Drone Trajectories */}
                            <div className="individual-drones-section">
                              <h5 className="section-title">🎯 Individual Drone Trajectories</h5>
                              <div className="drones-grid">
                                {/* Lead Drone */}
                                <div className="drone-preview-card">
                                  <div className="preview-header">
                                    <h6>Drone {leaderId}</h6>
                                    <div className="header-actions">
                                      <span className="drone-type-badge leader">LEAD</span>
                                      <button 
                                        className="delete-drone-btn"
                                        onClick={() => clearIndividualDrone(leaderId)}
                                        title="Delete this drone's trajectory"
                                      >
                                        🗑️
                                      </button>
                                    </div>
                                  </div>
                                  
                                  <div className="preview-plot clickable" onClick={() => openLightbox(`${getBackendURL()}/static/plots/drone_${leaderId}_trajectory.jpg`, `Drone ${leaderId} Trajectory`)}>
                                    <img 
                                      src={`${getBackendURL()}/static/plots/drone_${leaderId}_trajectory.jpg`}
                                      alt={`Drone ${leaderId} trajectory`}
                                      onError={(e) => {
                                        e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect width="100%" height="100%" fill="%23f0f0f0"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="%23666" text-anchor="middle">Plot Loading...</text></svg>';
                                      }}
                                    />
                                    <div className="zoom-overlay">
                                      <span className="zoom-icon">🔍</span>
                                    </div>
                                  </div>
                                  
                                  <div className="preview-actions">
                                    <button 
                                      className="preview-btn download"
                                      onClick={() => downloadDroneTrajectory(leaderId)}
                                      title="Download CSV"
                                    >
                                      <span className="btn-icon">⬇</span>
                                      CSV
                                    </button>
                                    <button 
                                      className="preview-btn kml"
                                      onClick={() => downloadDroneKML(leaderId)}
                                      title="Download KML"
                                    >
                                      <span className="btn-icon">🌍</span>
                                      KML
                                    </button>
                                    <button 
                                      className="preview-btn clear-single"
                                      onClick={() => clearSingleTrajectory(leaderId)}
                                      title="Clear cluster"
                                    >
                                      <span className="btn-icon">🗑</span>
                                      Clear
                                    </button>
                                  </div>
                                </div>

                                {/* Followers */}
                                {getFollowersForLeader(leaderId).map(followerId => (
                                  <div key={followerId} className="drone-preview-card">
                                    <div className="preview-header">
                                      <h6>Drone {followerId}</h6>
                                      <div className="header-actions">
                                        <span className="drone-type-badge follower">FOLLOW</span>
                                        <button 
                                          className="delete-drone-btn"
                                          onClick={() => clearIndividualDrone(followerId)}
                                          title="Delete this drone's trajectory"
                                        >
                                          🗑️
                                        </button>
                                      </div>
                                    </div>
                                    
                                    <div className="preview-plot clickable" onClick={() => openLightbox(`${getBackendURL()}/static/plots/drone_${followerId}_trajectory.jpg`, `Drone ${followerId} Trajectory`)}>
                                      <img 
                                        src={`${getBackendURL()}/static/plots/drone_${followerId}_trajectory.jpg`}
                                        alt={`Drone ${followerId} trajectory`}
                                        onError={(e) => {
                                          e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect width="100%" height="100%" fill="%23f7fafc"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="%2338a169" text-anchor="middle">Follower Plot</text></svg>';
                                        }}
                                      />
                                      <div className="zoom-overlay">
                                        <span className="zoom-icon">🔍</span>
                                      </div>
                                    </div>
                                    
                                    <div className="preview-actions">
                                      <button 
                                        className="preview-btn download"
                                        onClick={() => downloadDroneTrajectory(followerId)}
                                        title="Download CSV"
                                      >
                                        <span className="btn-icon">⬇</span>
                                        CSV
                                      </button>
                                      <button 
                                        className="preview-btn kml"
                                        onClick={() => downloadDroneKML(followerId)}
                                        title="Download KML"
                                      >
                                        <span className="btn-icon">🌍</span>
                                        KML
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </details>
                  </div>
                </div>
              ) : (
                <div className="error-card">
                  <span className="error-icon">❌</span>
                  <div>
                    <h4>Processing Failed</h4>
                    <p>{results.error}</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Utility Actions */}
          <div className="utility-actions">
            <button className="utility-btn" onClick={fetchStatus}>
              <span className="utility-icon">↻</span>
              Refresh Status
            </button>
            
            {results && results.processed_drones > 0 && (
              <button 
                className="utility-btn commit" 
                onClick={commitAndPushChanges}
                disabled={committing}
              >
                <span className="utility-icon">🚀</span>
                {committing ? 'Committing...' : 'Commit & Push Changes'}
              </button>
            )}
            
            <button className="utility-btn danger" onClick={clearAll}>
              <span className="utility-icon">🗑</span>
              Clear All Files
            </button>
          </div>
        </>
      ) : (
        /* No Lead Drones Found State */
        <div className="empty-state">
          <div className="empty-icon">🤖</div>
          <h3>No Clusters Found</h3>
          <p>Please check your swarm configuration. Make sure you have lead drones with follow=0 defined to create clusters.</p>
          <button className="utility-btn" onClick={fetchLeaders}>
            <span className="utility-icon">↻</span>
            Reload Configuration
          </button>
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
              />
            </div>
            <div className="lightbox-footer">
              <span className="lightbox-hint">Click outside or press ESC to close</span>
            </div>
          </div>
        </div>
      )}

      {/* Professional Progress Modal */}
      {commitProgress && (
        <div className="progress-overlay">
          <div className="progress-modal">
            <div className="progress-header">
              <h3>🚀 Committing Trajectory Changes</h3>
              <div className="progress-subtitle">
                Pushing {results?.processed_drones || 0} drone trajectories to repository...
              </div>
            </div>
            
            <div className="progress-content">
              <div className="progress-bar-container">
                <div 
                  className="progress-bar-fill" 
                  style={{ width: `${commitProgress.progress}%` }}
                ></div>
              </div>
              
              <div className="progress-step">
                {commitProgress.step}
              </div>
              
              <div className="progress-percentage">
                {commitProgress.progress}%
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SwarmTrajectory;