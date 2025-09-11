// src/components/VisualizationSection.js

import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
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
  Paper,
  Collapse,
  Modal,
  Tooltip,
  IconButton
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
  Psychology as PsychologyIcon,
  HelpOutline as HelpIcon
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
  const [showPerDroneData, setShowPerDroneData] = useState(false);

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

  // Format max altitude with enhanced details
  const formatMaxAltitude = () => {
    if (comprehensiveMetrics?.basic_metrics?.max_altitude_details) {
      const details = comprehensiveMetrics.basic_metrics.max_altitude_details;
      return `${details.value} m`;
    }
    if (showDetails.maxAltitude == null) return 'N/A';
    return `${Math.ceil(showDetails.maxAltitude * 10) / 10} m`; // Round up to 1 decimal
  };

  // Format minimum altitude with details
  const formatMinAltitude = () => {
    if (comprehensiveMetrics?.basic_metrics?.min_altitude_details) {
      const details = comprehensiveMetrics.basic_metrics.min_altitude_details;
      return `${details.value} m`;
    }
    return 'N/A';
  };

  // Format max speed with details
  const formatMaxSpeed = () => {
    if (comprehensiveMetrics?.performance_metrics?.max_velocity_details) {
      const details = comprehensiveMetrics.performance_metrics.max_velocity_details;
      return `${details.value} m/s`;
    }
    return 'N/A';
  };

  // Format max distance from launch with details
  const formatMaxDistance = () => {
    if (comprehensiveMetrics?.basic_metrics?.max_distance_details) {
      const details = comprehensiveMetrics.basic_metrics.max_distance_details;
      return `${details.value} m`;
    }
    return 'N/A';
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

  const renderTechnicalData = () => {
    if (!comprehensiveMetrics) return null;

    const { basic_metrics, safety_metrics, performance_metrics, formation_metrics, quality_metrics } = comprehensiveMetrics;

    return (
      <Box sx={{ mt: 4 }}>
        <Divider sx={{ my: 3 }} />
        
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
          <Typography variant="h6" sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
            <PsychologyIcon />
            Technical Analysis Data
          </Typography>
          <Button
            variant="outlined"
            onClick={() => setShowAdvancedMetrics(!showAdvancedMetrics)}
            endIcon={<ExpandMoreIcon sx={{ transform: showAdvancedMetrics ? 'rotate(180deg)' : 'none', transition: '0.3s' }} />}
            sx={{ borderColor: '#0056b3', color: '#0056b3' }}
          >
            {showAdvancedMetrics ? 'Hide Technical Data' : 'Show Technical Data'}
          </Button>
        </Box>

        {/* Collapsible Technical Details */}
        <Collapse in={showAdvancedMetrics}>
          <Box sx={{ mb: 3 }}>
            <Button
              variant="outlined"
              onClick={() => setShowPerDroneData(!showPerDroneData)}
              sx={{ borderColor: '#0056b3', color: '#0056b3', mb: 2 }}
            >
              {showPerDroneData ? 'Hide Per-Drone Data' : 'Show Per-Drone Data'}
            </Button>
            
            <Collapse in={showPerDroneData}>
              <Paper sx={{ p: 3, mb: 3, bgcolor: '#f8f9fa', border: '1px solid #e9ecef' }}>
                <Typography variant="h6" gutterBottom sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
                  <TheatersIcon />
                  Individual Drone Analysis
                </Typography>
                {comprehensiveMetrics?.performance_metrics?.per_drone_velocity && (
                  <Grid container spacing={2}>
                    {Object.entries(comprehensiveMetrics.performance_metrics.per_drone_velocity).map(([droneId, data]) => (
                      <Grid item xs={12} sm={6} md={4} key={droneId}>
                        <Paper sx={{ p: 2, border: '1px solid #dee2e6' }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#0056b3', mb: 1 }}>
                            Drone {droneId}
                          </Typography>
                          <List dense>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Max Speed" 
                                secondary={`${data.max_velocity_ms} m/s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Avg Speed" 
                                secondary={`${data.avg_velocity_ms} m/s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Speed Variation" 
                                secondary={`±${data.velocity_std_ms} m/s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                          </List>
                        </Paper>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </Paper>
            </Collapse>
          </Box>
          
          <Grid container spacing={3}>
            {/* Safety Analysis */}
            {safety_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={{ p: 3, height: '100%', bgcolor: '#fafbfc', border: '1px solid #e9ecef' }}>
                  <Typography variant="h6" gutterBottom sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <SecurityIcon />
                    Safety Analysis
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Ground Clearance (Min)" 
                        secondary={`${safety_metrics.min_ground_clearance_m} m`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Inter-Drone Distance (Min)" 
                        secondary={typeof safety_metrics.min_inter_drone_distance_m === 'number' 
                          ? `${safety_metrics.min_inter_drone_distance_m} m` 
                          : safety_metrics.min_inter_drone_distance_m}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Collision Warnings" 
                        secondary={`${safety_metrics.collision_warnings_count || 0} detected`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Performance Analysis */}
            {performance_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={{ p: 3, height: '100%', bgcolor: '#fafbfc', border: '1px solid #e9ecef' }}>
                  <Typography variant="h6" gutterBottom sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <SpeedIcon />
                    Performance Analysis
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Velocity" 
                        secondary={`${performance_metrics.max_velocity_ms} m/s (${performance_metrics.max_velocity_kmh} km/h)`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Acceleration" 
                        secondary={`${performance_metrics.max_acceleration_ms2} m/s²`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Performance Status" 
                        secondary={performance_metrics.performance_status}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Formation Analysis */}
            {formation_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={{ p: 3, height: '100%', bgcolor: '#fafbfc', border: '1px solid #e9ecef' }}>
                  <Typography variant="h6" gutterBottom sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <TimelineIcon />
                    Formation Analysis
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Formation Coherence" 
                        secondary={`${(formation_metrics.formation_coherence_score * 100).toFixed(1)}%`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Formation Complexity" 
                        secondary={formation_metrics.formation_complexity}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Swarm Center Movement" 
                        secondary={`${formation_metrics.swarm_center_total_movement_m} m total`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                  </List>
                </Paper>
              </Grid>
            )}

            {/* Quality & Recommendations */}
            {quality_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={{ p: 3, height: '100%', bgcolor: '#fafbfc', border: '1px solid #e9ecef' }}>
                  <Typography variant="h6" gutterBottom sx={{ color: '#0056b3', display: 'flex', alignItems: 'center', gap: 1 }}>
                    <AssessmentIcon />
                    Quality Assessment
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Trajectory Smoothness" 
                        secondary={`${(quality_metrics.trajectory_smoothness_score * 100).toFixed(1)}%`}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Overall Quality Rating" 
                        secondary={quality_metrics.overall_quality_rating}
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    {quality_metrics.recommendations && quality_metrics.recommendations.slice(0, 2).map((rec, idx) => (
                      <ListItem key={idx} sx={{ px: 0 }}>
                        <ListItemText 
                          primary={rec}
                          primaryTypographyProps={{ variant: 'body2', color: 'textSecondary' }}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              </Grid>
            )}
          </Grid>
        </Collapse>
      </Box>
    );
  };

  return (
    <Box className="visualization-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Drone Show Visualization
      </Typography>

      {/* Essential Metrics - Always Visible */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <AccessTimeIcon color="primary" sx={{ fontSize: 40, mb: 1 }} />
              <Typography variant="subtitle2" color="textSecondary" gutterBottom>
                Duration
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {formatDuration()}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <TheatersIcon color="secondary" sx={{ fontSize: 40, mb: 1 }} />
              <Typography variant="subtitle2" color="textSecondary" gutterBottom>
                Drone Count
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {showDetails.droneCount || 'N/A'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <HeightIcon color="success" sx={{ fontSize: 40, mb: 1 }} />
              <Tooltip title="Maximum altitude reached during the entire show">
                <Typography variant="subtitle2" color="textSecondary" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Altitude <HelpIcon sx={{ fontSize: 16 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {formatMaxAltitude()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.max_altitude_details && (
                <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.max_altitude_details.drone_id} at {comprehensiveMetrics.basic_metrics.max_altitude_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Min Altitude Card */}
        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <HeightIcon color="warning" sx={{ fontSize: 40, mb: 1, transform: 'rotate(180deg)' }} />
              <Tooltip title="Minimum altitude during flight phase (excluding takeoff/landing)">
                <Typography variant="subtitle2" color="textSecondary" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Min Altitude <HelpIcon sx={{ fontSize: 16 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {formatMinAltitude()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.min_altitude_details && (
                <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.min_altitude_details.drone_id} at {comprehensiveMetrics.basic_metrics.min_altitude_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Max Speed Card */}
        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <SpeedIcon color="info" sx={{ fontSize: 40, mb: 1 }} />
              <Tooltip title="Maximum velocity reached by any drone during the show">
                <Typography variant="subtitle2" color="textSecondary" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Speed <HelpIcon sx={{ fontSize: 16 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {formatMaxSpeed()}
              </Typography>
              {comprehensiveMetrics?.performance_metrics?.max_velocity_details && (
                <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                  Drone {comprehensiveMetrics.performance_metrics.max_velocity_details.drone_id} at {comprehensiveMetrics.performance_metrics.max_velocity_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Max Distance from Launch */}
        <Grid item xs={12} sm={6} md={4} lg={2}>
          <Card variant="outlined" sx={{ height: '100%', border: '2px solid #e9ecef', borderRadius: 2 }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <TimelineIcon color="secondary" sx={{ fontSize: 40, mb: 1 }} />
              <Tooltip title="Maximum distance any drone traveled from its launch position during the show">
                <Typography variant="subtitle2" color="textSecondary" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Distance <HelpIcon sx={{ fontSize: 16 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                {formatMaxDistance()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.max_distance_details && (
                <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.max_distance_details.drone_id} at {comprehensiveMetrics.basic_metrics.max_distance_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Advanced Metrics Row - Only if comprehensive metrics available */}
      {comprehensiveMetrics && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          {comprehensiveMetrics.performance_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined" sx={{ height: '100%', bgcolor: '#f8f9fa' }}>
                <CardContent sx={{ textAlign: 'center', py: 2 }}>
                  <SpeedIcon color="primary" sx={{ fontSize: 30, mb: 1 }} />
                  <Typography variant="caption" color="textSecondary" display="block">
                    Max Speed
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                    {comprehensiveMetrics.performance_metrics.max_velocity_ms} m/s
                  </Typography>
                  <Typography variant="caption" color="textSecondary">
                    ({comprehensiveMetrics.performance_metrics.max_velocity_kmh} km/h)
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          )}

          {comprehensiveMetrics.safety_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined" sx={{ height: '100%', bgcolor: '#f8f9fa' }}>
                <CardContent sx={{ textAlign: 'center', py: 2 }}>
                  <SecurityIcon color="success" sx={{ fontSize: 30, mb: 1 }} />
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, justifyContent: 'center' }}>
                    <Typography variant="caption" color="textSecondary">
                      Min Profile
                    </Typography>
                    <Tooltip title="Minimum separation distance between any two drones during the entire show. Safe operation requires >2m separation." arrow>
                      <HelpIcon sx={{ fontSize: 12, color: '#6c757d' }} />
                    </Tooltip>
                  </Box>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                    {typeof comprehensiveMetrics.safety_metrics.min_inter_drone_distance_m === 'number' 
                      ? `${comprehensiveMetrics.safety_metrics.min_inter_drone_distance_m} m` 
                      : 'N/A'}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          )}

          {comprehensiveMetrics.safety_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined" sx={{ 
                height: '100%', 
                bgcolor: '#f8f9fa',
                border: comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' 
                  ? '2px solid #28a745' 
                  : comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION'
                  ? '2px solid #ffc107'
                  : '1px solid #e9ecef'
              }}>
                <CardContent sx={{ textAlign: 'center', py: 2 }}>
                  <SecurityIcon 
                    sx={{ 
                      fontSize: 30, 
                      mb: 1,
                      color: comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' 
                        ? '#28a745' 
                        : comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION'
                        ? '#ffc107'
                        : '#6c757d'
                    }} 
                  />
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                    <Typography variant="caption" color="textSecondary" display="block">
                      Safety Status
                    </Typography>
                    <Tooltip title="Safety assessment based on collision risk analysis, ground clearance, and inter-drone distances. SAFE = No collision warnings, proper clearances maintained." arrow>
                      <HelpIcon sx={{ fontSize: 12, color: '#6c757d' }} />
                    </Tooltip>
                  </Box>
                  <Chip 
                    label={comprehensiveMetrics?.safety_metrics?.safety_status || 'Analyzing...'} 
                    color={
                      comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' ? 'success' :
                      comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION' ? 'warning' : 'default'
                    }
                    size="small"
                    sx={{ fontWeight: 'bold', fontSize: '0.75rem' }}
                  />
                </CardContent>
              </Card>
            </Grid>
          )}

          {comprehensiveMetrics.formation_metrics && (
            <Grid item xs={12} sm={6} md={3}>
              <Card variant="outlined" sx={{ height: '100%', bgcolor: '#f8f9fa' }}>
                <CardContent sx={{ textAlign: 'center', py: 2 }}>
                  <TimelineIcon color="secondary" sx={{ fontSize: 30, mb: 1 }} />
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, justifyContent: 'center' }}>
                    <Typography variant="caption" color="textSecondary">
                      Formation Quality
                    </Typography>
                    <Tooltip title="Formation coherence score based on how well drones maintain their relative positions. Higher percentage indicates better synchronized movement." arrow>
                      <HelpIcon sx={{ fontSize: 12, color: '#6c757d' }} />
                    </Tooltip>
                  </Box>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#0056b3' }}>
                    {(comprehensiveMetrics.formation_metrics.formation_coherence_score * 100).toFixed(0)}%
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && (
        <Typography variant="body1" color="error" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}

      {/* Combined Plot - All Drones Together */}
      {plots.some(name => name === 'combined_drone_paths.jpg') && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ color: '#0056b3', mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            <AssessmentIcon />
            All Drones Combined View
          </Typography>
          <Paper sx={{ p: 1, textAlign: 'center' }}>
            <Box
              className="clickable-image"
              onClick={() => openModal(plots.findIndex(name => name === 'combined_drone_paths.jpg'))}
              sx={{ 
                cursor: 'pointer',
                transition: 'transform 0.3s ease',
                '&:hover': { transform: 'scale(1.02)' }
              }}
            >
              <img 
                src={`${backendURL}/get-show-plots/combined_drone_paths.jpg`} 
                alt="All Drones Combined Trajectory" 
                style={{ 
                  width: '100%', 
                  maxWidth: '800px',
                  height: 'auto',
                  borderRadius: '8px',
                  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)'
                }} 
              />
            </Box>
            <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
              Click to view in full screen
            </Typography>
          </Paper>
        </Box>
      )}

      {/* Individual Drone Plots */}
      {plots.filter(name => name !== 'combined_drone_paths.jpg').length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ color: '#0056b3', mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            <TimelineIcon />
            Individual Drone Trajectories
          </Typography>
          <Box className="plot-grid" sx={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', 
            gap: 2 
          }}>
            {plots
              .filter((name) => name !== 'combined_drone_paths.jpg')
              .map((plot, index) => {
                const plotUrl = `${backendURL}/get-show-plots/${encodeURIComponent(plot)}`;
                const droneId = plot.match(/drone_(\d+)_path/)?.[1] || index + 1;
                return (
                  <Paper key={`individual-${index}`} sx={{ p: 1 }}>
                    <Typography variant="subtitle2" sx={{ mb: 1, textAlign: 'center', color: '#0056b3' }}>
                      Drone {droneId}
                    </Typography>
                    <Box
                      className="clickable-image"
                      onClick={() => openModal(plots.findIndex(p => p === plot))}
                      sx={{ 
                        cursor: 'pointer',
                        transition: 'transform 0.3s ease',
                        '&:hover': { transform: 'scale(1.05)' }
                      }}
                    >
                      <img 
                        src={plotUrl} 
                        alt={`Drone ${droneId} Trajectory`} 
                        style={{ 
                          width: '100%', 
                          height: 'auto',
                          borderRadius: '6px',
                          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)'
                        }}
                      />
                    </Box>
                  </Paper>
                );
              })}
          </Box>
        </Box>
      )}

      {/* Professional Lightbox Modal */}
      <Modal 
        open={isModalOpen} 
        onClose={closeModal}
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          p: 2,
          bgcolor: 'rgba(0, 0, 0, 0.9)',
          backdropFilter: 'blur(4px)'
        }}
      >
        <Box sx={{
          position: 'relative',
          maxWidth: '95vw',
          maxHeight: '95vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          outline: 'none'
        }}>
          {/* Close Button */}
          <Button
            onClick={closeModal}
            sx={{
              position: 'absolute',
              top: -10,
              right: -10,
              minWidth: 40,
              width: 40,
              height: 40,
              borderRadius: '50%',
              bgcolor: 'rgba(255, 255, 255, 0.9)',
              color: '#333',
              zIndex: 1000,
              '&:hover': { bgcolor: 'white' }
            }}
          >
            ✕
          </Button>

          {plots.length > 1 && (
            <>
              {/* Previous Button */}
              <Button
                onClick={showPrevious}
                sx={{
                  position: 'absolute',
                  left: -60,
                  minWidth: 50,
                  width: 50,
                  height: 50,
                  borderRadius: '50%',
                  bgcolor: 'rgba(255, 255, 255, 0.9)',
                  color: '#333',
                  fontSize: '20px',
                  zIndex: 1000,
                  '&:hover': { bgcolor: 'white' }
                }}
              >
                ‹
              </Button>

              {/* Next Button */}
              <Button
                onClick={showNext}
                sx={{
                  position: 'absolute',
                  right: -60,
                  minWidth: 50,
                  width: 50,
                  height: 50,
                  borderRadius: '50%',
                  bgcolor: 'rgba(255, 255, 255, 0.9)',
                  color: '#333',
                  fontSize: '20px',
                  zIndex: 1000,
                  '&:hover': { bgcolor: 'white' }
                }}
              >
                ›
              </Button>
            </>
          )}

          {/* Image Container */}
          <Box sx={{
            maxWidth: '100%',
            maxHeight: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            bgcolor: 'white',
            borderRadius: 2,
            overflow: 'hidden',
            boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)'
          }}>
            {plots.length > 0 && (
              <>
                <img
                  src={`${backendURL}/get-show-plots/${encodeURIComponent(plots[currentIndex] || '')}`}
                  alt={`Drone Trajectory Plot ${currentIndex + 1}`}
                  style={{
                    maxWidth: '100%',
                    maxHeight: 'calc(95vh - 60px)',
                    width: 'auto',
                    height: 'auto',
                    display: 'block'
                  }}
                />
                
                {/* Image Info */}
                <Box sx={{ p: 2, bgcolor: '#f8f9fa', width: '100%', textAlign: 'center' }}>
                  <Typography variant="subtitle1" sx={{ color: '#0056b3', fontWeight: 'bold' }}>
                    {plots[currentIndex]?.includes('combined') 
                      ? 'All Drones Combined View' 
                      : `Drone ${plots[currentIndex]?.match(/drone_(\d+)_path/)?.[1] || currentIndex + 1} Trajectory`
                    }
                  </Typography>
                  {plots.length > 1 && (
                    <Typography variant="caption" color="textSecondary">
                      {currentIndex + 1} of {plots.length} plots
                    </Typography>
                  )}
                </Box>
              </>
            )}
          </Box>
        </Box>
      </Modal>

      {/* Render Technical Data */}
      {renderTechnicalData()}
    </Box>
  );
};

export default VisualizationSection;
