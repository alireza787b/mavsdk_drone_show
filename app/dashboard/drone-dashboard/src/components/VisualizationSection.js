// src/components/VisualizationSection.js

import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
import Modal from './Modal';
import {
  Box,
  Typography,
  Card,
  CardHeader,
  CardContent,
  Grid,
  LinearProgress,
  Button,
  Chip,
  Divider,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper
} from '@mui/material';
import {
  AccessTime as AccessTimeIcon,
  Theaters as TheatersIcon,
  Speed as SpeedIcon,
  Security as SecurityIcon,
  Assessment as AssessmentIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  ExpandMore as ExpandMoreIcon,
  Timeline as TimelineIcon,
  Psychology as PsychologyIcon
} from '@mui/icons-material';
import HeightIcon from '@mui/icons-material/Height';

const VisualizationSection = ({ uploadCount }) => {
  const [plots, setPlots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const [showDetails, setShowDetails] = useState({
    droneCount: 0,
    duration: null,
    maxAltitude: null,
  });
  const [comprehensiveMetrics, setComprehensiveMetrics] = useState(null);
  const [showAdvancedMetrics, setShowAdvancedMetrics] = useState(false);

  const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

  useEffect(() => {
    const fetchShowData = async () => {
      setLoading(true);
      setError('');
      try {
        // Fetch plots
        const plotsResponse = await fetch(`${backendURL}/get-show-plots`);
        const plotsData = await plotsResponse.json();

        if (!plotsResponse.ok) {
          throw new Error(plotsData.error || 'Failed to fetch plots');
        }

        const filenames = plotsData.filenames || [];
        setPlots(filenames);

        // Fetch show info
        const showInfoResponse = await fetch(`${backendURL}/get-show-info`);
        const showInfoData = await showInfoResponse.json();

        setShowDetails({
          droneCount: showInfoData.drone_count,
          duration: {
            ms: showInfoData.duration_ms,
            minutes: parseInt(showInfoData.duration_minutes),
            seconds: parseInt(showInfoData.duration_seconds),
          },
          maxAltitude: showInfoData.max_altitude,
        });

        // Fetch comprehensive metrics (new endpoint)
        try {
          const metricsResponse = await fetch(`${backendURL}/get-comprehensive-metrics`);
          if (metricsResponse.ok) {
            const metricsData = await metricsResponse.json();
            setComprehensiveMetrics(metricsData);
          }
        } catch (metricsError) {
          console.log('Comprehensive metrics not available:', metricsError);
        }
      } catch (err) {
        console.error('Error fetching data:', err.message);
        setError(err.message);
        setPlots([]);
      } finally {
        setLoading(false);
      }
    };

    fetchShowData();
  }, [uploadCount, backendURL]);

  // Format duration with no decimal seconds
  const formatDuration = () => {
    const { duration } = showDetails;
    if (!duration) return 'N/A';
    return `${duration.minutes}m ${duration.seconds}s`; // No decimals
  };

  // Format max altitude with rounding up to 1 decimal
  const formatMaxAltitude = () => {
    if (showDetails.maxAltitude == null) return 'N/A';
    return `${Math.ceil(showDetails.maxAltitude * 10) / 10} m`; // Round up to 1 decimal
  };

  const openModal = (index) => {
    setCurrentIndex(index);
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
  };

  const showPrevious = () => {
    const previousIndex = currentIndex === 0 ? plots.length - 1 : currentIndex - 1;
    setCurrentIndex(previousIndex);
  };

  const showNext = () => {
    const nextIndex = currentIndex === plots.length - 1 ? 0 : currentIndex + 1;
    setCurrentIndex(nextIndex);
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'SAFE': case 'EXCELLENT': return 'success';
      case 'GOOD': return 'info';
      case 'CAUTION': case 'NEEDS_IMPROVEMENT': return 'warning';
      case 'HIGH_SPEED': case 'HIGH_ACCELERATION': return 'secondary';
      default: return 'default';
    }
  };

  const renderComprehensiveMetrics = () => {
    if (!comprehensiveMetrics) return null;

    const { basic_metrics, safety_metrics, performance_metrics, formation_metrics, quality_metrics } = comprehensiveMetrics;

    return (
      <Box sx={{ mt: 3 }}>
        <Divider sx={{ my: 2 }} />
        
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6" sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
            <PsychologyIcon />
            Comprehensive Analysis
          </Typography>
          <Button
            variant="outlined"
            onClick={() => setShowAdvancedMetrics(!showAdvancedMetrics)}
            endIcon={<ExpandMoreIcon sx={{ transform: showAdvancedMetrics ? 'rotate(180deg)' : 'none', transition: '0.3s' }} />}
          >
            {showAdvancedMetrics ? 'Hide Details' : 'Show Details'}
          </Button>
        </Box>

        {/* Safety Status Alert */}
        {safety_metrics && (
          <Alert 
            severity={safety_metrics.safety_status === 'SAFE' ? 'success' : 'warning'}
            sx={{ mb: 2 }}
          >
            <strong>Safety Status: {safety_metrics.safety_status}</strong>
            {safety_metrics.collision_warnings_count > 0 && (
              <span> - {safety_metrics.collision_warnings_count} collision warnings detected</span>
            )}
          </Alert>
        )}

        {/* Performance & Quality Overview */}
        <Grid container spacing={2} sx={{ mb: 2 }}>
          {performance_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined">
                <CardHeader
                  avatar={<SpeedIcon color="primary" />}
                  title="Max Speed"
                />
                <CardContent>
                  <Typography variant="h6">{performance_metrics.max_velocity_ms} m/s</Typography>
                  <Typography variant="body2" color="textSecondary">
                    ({performance_metrics.max_velocity_kmh} km/h)
                  </Typography>
                  <Chip 
                    label={performance_metrics.performance_status} 
                    color={getStatusColor(performance_metrics.performance_status)}
                    size="small"
                    sx={{ mt: 1 }}
                  />
                </CardContent>
              </Card>
            </Grid>
          )}

          {safety_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined">
                <CardHeader
                  avatar={<SecurityIcon color="success" />}
                  title="Min Distance"
                />
                <CardContent>
                  <Typography variant="h6">
                    {typeof safety_metrics.min_inter_drone_distance_m === 'number' 
                      ? `${safety_metrics.min_inter_drone_distance_m} m` 
                      : safety_metrics.min_inter_drone_distance_m}
                  </Typography>
                  <Chip 
                    label={safety_metrics.safety_status} 
                    color={getStatusColor(safety_metrics.safety_status)}
                    size="small"
                    sx={{ mt: 1 }}
                  />
                </CardContent>
              </Card>
            </Grid>
          )}

          {formation_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined">
                <CardHeader
                  avatar={<TimelineIcon color="secondary" />}
                  title="Formation Quality"
                />
                <CardContent>
                  <Typography variant="h6">{(formation_metrics.formation_coherence_score * 100).toFixed(1)}%</Typography>
                  <Chip 
                    label={formation_metrics.formation_quality} 
                    color={getStatusColor(formation_metrics.formation_quality)}
                    size="small"
                    sx={{ mt: 1 }}
                  />
                </CardContent>
              </Card>
            </Grid>
          )}

          {quality_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined">
                <CardHeader
                  avatar={<AssessmentIcon color="info" />}
                  title="Overall Quality"
                />
                <CardContent>
                  <Typography variant="h6">{(quality_metrics.quality_score * 100).toFixed(1)}%</Typography>
                  <Chip 
                    label={quality_metrics.overall_quality_rating} 
                    color={getStatusColor(quality_metrics.overall_quality_rating)}
                    size="small"
                    sx={{ mt: 1 }}
                  />
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>

        {/* Detailed Metrics (Collapsible) */}
        {showAdvancedMetrics && (
          <Grid container spacing={2}>
            {/* Safety Details */}
            {safety_metrics && (
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <SecurityIcon color="success" />
                    Safety Analysis
                  </Typography>
                  <List dense>
                    <ListItem>
                      <ListItemText 
                        primary="Ground Clearance" 
                        secondary={`${safety_metrics.min_ground_clearance_m} m minimum`}
                      />
                    </ListItem>
                    {safety_metrics.collision_warnings && safety_metrics.collision_warnings.length > 0 && (
                      <ListItem>
                        <ListItemIcon>
                          <WarningIcon color="warning" />
                        </ListItemIcon>
                        <ListItemText 
                          primary="Collision Warnings" 
                          secondary={`${safety_metrics.collision_warnings_count} warnings detected`}
                        />
                      </ListItem>
                    )}
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Performance Details */}
            {performance_metrics && (
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <SpeedIcon color="primary" />
                    Performance Metrics
                  </Typography>
                  <List dense>
                    <ListItem>
                      <ListItemText 
                        primary="Max Acceleration" 
                        secondary={`${performance_metrics.max_acceleration_ms2} m/s²`}
                      />
                    </ListItem>
                    <ListItem>
                      <ListItemText 
                        primary="Est. Battery Usage" 
                        secondary={`${performance_metrics.estimated_battery_usage_percent}%`}
                      />
                    </ListItem>
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Formation Details */}
            {formation_metrics && (
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <TimelineIcon color="secondary" />
                    Formation Analysis
                  </Typography>
                  <List dense>
                    <ListItem>
                      <ListItemText 
                        primary="Formation Complexity" 
                        secondary={formation_metrics.formation_complexity}
                      />
                    </ListItem>
                    <ListItem>
                      <ListItemText 
                        primary="Swarm Movement" 
                        secondary={`${formation_metrics.swarm_center_total_movement_m} m total`}
                      />
                    </ListItem>
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Quality & Recommendations */}
            {quality_metrics && (
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 2 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <AssessmentIcon color="info" />
                    Quality & Recommendations
                  </Typography>
                  <List dense>
                    <ListItem>
                      <ListItemText 
                        primary="Trajectory Smoothness" 
                        secondary={`${(quality_metrics.trajectory_smoothness_score * 100).toFixed(1)}%`}
                      />
                    </ListItem>
                    {quality_metrics.recommendations && quality_metrics.recommendations.map((rec, idx) => (
                      <ListItem key={idx}>
                        <ListItemIcon>
                          <CheckCircleIcon color="info" sx={{ fontSize: 16 }} />
                        </ListItemIcon>
                        <ListItemText 
                          primary={rec}
                          primaryTypographyProps={{ variant: 'body2' }}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              </Grid>
            )}
          </Grid>
        )}
      </Box>
    );
  };

  return (
    <Box className="visualization-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Drone Show Visualization
      </Typography>

      {/* Show Details (Duration, Drone Count, Max Altitude) */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={6} md={4}>
          <Card variant="outlined">
            <CardHeader 
              avatar={<AccessTimeIcon color="primary" fontSize="large" />} 
              title="Show Duration" 
            />
            <CardContent>
              <Typography variant="h6">
                {formatDuration()}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={4}>
          <Card variant="outlined">
            <CardHeader 
              avatar={<TheatersIcon color="secondary" fontSize="large" />} 
              title="Drone Count" 
            />
            <CardContent>
              <Typography variant="h6">
                {showDetails.droneCount || 'N/A'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* New card for Maximum Altitude */}
        <Grid item xs={12} sm={6} md={4}>
          <Card variant="outlined">
            <CardHeader
              avatar={<HeightIcon color="success" fontSize="large" />}
              title="Max Altitude"
            />
            <CardContent>
              <Typography variant="h6">
                {formatMaxAltitude()}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && (
        <Typography variant="body1" color="error" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}

      {/* Render the Combined Plot (if it exists) */}
      {plots
        .filter((name) => name === 'combined_drone_paths.jpg')
        .map((plot, index) => {
          const plotUrl = `${backendURL}/get-show-plots/${encodeURIComponent(plot)}`;
          return (
            <Box
              key={`combined-${index}`}
              className="plot-full-width clickable-image"
              onClick={() => openModal(0)}
              sx={{ mb: 3 }}
            >
              <img src={plotUrl} alt="All Drones" style={{ width: '80%' }} />
            </Box>
          );
        })}

      {/* Individual Plots in a Grid */}
      <Box className="plot-grid">
        {plots
          .filter((name) => name !== 'combined_drone_paths.jpg')
          .map((plot, index) => {
            const plotUrl = `${backendURL}/get-show-plots/${encodeURIComponent(plot)}`;
            return (
              <Box
                key={`individual-${index}`}
                className="plot clickable-image"
                onClick={() => openModal(index + 1)}
              >
                <img src={plotUrl} alt={`Plot ${index}`} />
              </Box>
            );
          })}
      </Box>

      {/* Modal for displaying the selected image */}
      <Modal isOpen={isModalOpen} onClose={closeModal}>
        {plots.length > 0 && (
          <Box className="modal-image-container">
            <Button
              className="nav-button prev-button"
              onClick={showPrevious}
              aria-label="Previous Image"
            >
              &#10094;
            </Button>
            <Box className="modal-image-wrapper">
              <img
                src={`${backendURL}/get-show-plots/${encodeURIComponent(
                  plots[currentIndex] || ''
                )}`}
                alt={`Plot ${currentIndex}`}
                className="modal-image"
              />
            </Box>
            <Button
              className="nav-button next-button"
              onClick={showNext}
              aria-label="Next Image"
            >
              &#10095;
            </Button>
          </Box>
        )}
      </Modal>

      {/* Render Comprehensive Metrics */}
      {renderComprehensiveMetrics()}
    </Box>
  );
};

export default VisualizationSection;
