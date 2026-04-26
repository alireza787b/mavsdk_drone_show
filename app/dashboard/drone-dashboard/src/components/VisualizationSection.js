// src/components/VisualizationSection.js

import React, { useState, useEffect } from 'react';
import {
  Alert,
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Button,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  Collapse,
  Modal,
  Tooltip,
  CircularProgress
} from '@mui/material';
import {
  AccessTime as AccessTimeIcon,
  Theaters as TheatersIcon,
  Speed as SpeedIcon,
  Security as SecurityIcon,
  Timeline as TimelineIcon,
  Psychology as PsychologyIcon,
  HelpOutline as HelpIcon,
  ExpandMore as ExpandMoreIcon,
  Assessment as AssessmentIcon
} from '@mui/icons-material';
import HeightIcon from '@mui/icons-material/Height';
import { extractApiErrorMessage } from '../services/apiError';
import {
  buildShowPlotUrl,
  getComprehensiveMetricsResponse,
  getShowInfoResponse,
  getShowPlotsResponse,
} from '../services/gcsApiService';

const VIS_TOKENS = {
  border: 'var(--color-border-primary)',
  borderSecondary: 'var(--color-border-secondary)',
  overlay: 'var(--color-bg-overlay)',
  primary: 'var(--color-primary)',
  surface: 'var(--color-bg-secondary)',
  surfaceRaised: 'var(--color-bg-tertiary)',
  success: 'var(--color-success)',
  text: 'var(--color-text-primary)',
  textSecondary: 'var(--color-text-secondary)',
  warning: 'var(--color-warning)',
};

const analysisHeadingSx = {
  color: VIS_TOKENS.primary,
  display: 'flex',
  alignItems: 'center',
  gap: 1,
};

const analysisPanelSx = {
  bgcolor: VIS_TOKENS.surface,
  border: `1px solid ${VIS_TOKENS.border}`,
};

const technicalPanelSx = {
  p: 3,
  height: '100%',
  bgcolor: VIS_TOKENS.surface,
  border: `1px solid ${VIS_TOKENS.border}`,
};

const primaryOutlineButtonSx = {
  borderColor: VIS_TOKENS.primary,
  color: VIS_TOKENS.primary,
};

const plotImageStyle = {
  width: '100%',
  height: 'auto',
  borderRadius: '8px',
  boxShadow: 'var(--shadow-sm)',
};

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

  useEffect(() => {
    let isActive = true;

    const fetchShowData = async () => {
      setLoading(true);
      setError('');
      try {
        const [plotsResponse, showInfoResponse] = await Promise.all([
          getShowPlotsResponse(),
          getShowInfoResponse(),
        ]);

        const plotsData = plotsResponse.data || {};
        const showInfoData = showInfoResponse.data || {};
        const filenames = plotsData.filenames || [];

        if (!isActive) {
          return;
        }

        setPlots(filenames);

        if (Number(showInfoData?.drone_count || 0) > 0) {
          setShowDetails({
            droneCount: showInfoData.drone_count,
            duration: {
              ms: showInfoData.duration_ms,
              minutes: parseInt(showInfoData.duration_minutes),
              seconds: parseInt(showInfoData.duration_seconds),
            },
            maxAltitude: showInfoData.max_altitude,
          });
        } else {
          setShowDetails({
            droneCount: 0,
            duration: null,
            maxAltitude: null,
          });
          setComprehensiveMetrics(null);
        }

        try {
          if (Number(showInfoData?.drone_count || 0) > 0) {
            const metricsResponse = await getComprehensiveMetricsResponse();
            const metricsData = metricsResponse.data || null;
            if (!isActive) {
              return;
            }
            setComprehensiveMetrics(metricsData);
          } else if (isActive) {
            setComprehensiveMetrics(null);
          }
        } catch {
          if (isActive) {
            setComprehensiveMetrics(null);
          }
        }
      } catch (err) {
        if (!isActive) {
          return;
        }
        const message = await extractApiErrorMessage(err, 'Failed to fetch show visualization data');
        setError(message);
        setPlots([]);
        setComprehensiveMetrics(null);
      } finally {
        if (isActive) {
          setLoading(false);
        }
      }
    };

    fetchShowData();
    return () => {
      isActive = false;
    };
  }, [uploadCount]);

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

  const hasImportedShow = showDetails.droneCount > 0 || plots.length > 0 || Boolean(comprehensiveMetrics);


  const renderTechnicalData = () => {
    if (!comprehensiveMetrics) return null;

    const { safety_metrics, performance_metrics, quality_metrics } = comprehensiveMetrics;

    return (
      <Box sx={{ mt: 4 }}>
        <Divider sx={{ my: 3 }} />
        
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
          <Typography variant="h6" sx={analysisHeadingSx}>
            <PsychologyIcon />
            Technical Analysis Data
          </Typography>
          <Button
            variant="outlined"
            onClick={() => setShowAdvancedMetrics(!showAdvancedMetrics)}
            endIcon={<ExpandMoreIcon sx={{ transform: showAdvancedMetrics ? 'rotate(180deg)' : 'none', transition: '0.3s' }} />}
            sx={primaryOutlineButtonSx}
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
              sx={{ ...primaryOutlineButtonSx, mb: 2 }}
            >
              {showPerDroneData ? 'Hide Per-Drone Data' : 'Show Per-Drone Data'}
            </Button>
            
            <Collapse in={showPerDroneData}>
              <Paper sx={{ p: 3, mb: 3, ...analysisPanelSx }}>
                <Typography variant="h6" gutterBottom sx={analysisHeadingSx}>
                  <TheatersIcon />
                  Individual Drone Analysis
                </Typography>
                {comprehensiveMetrics?.basic_metrics?.per_drone_metrics && (
                  <Grid container spacing={2}>
                    {Object.entries(comprehensiveMetrics.basic_metrics.per_drone_metrics).map(([droneId, data]) => {
                      const velocityData = comprehensiveMetrics?.performance_metrics?.per_drone_velocity?.[droneId];
                      return (
                      <Grid item xs={12} sm={6} md={4} key={droneId}>
                        <Paper sx={{ p: 2, border: `1px solid ${VIS_TOKENS.borderSecondary}` }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: VIS_TOKENS.primary, mb: 1 }}>
                            Drone {droneId}
                          </Typography>
                          <List dense>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Max Altitude" 
                                secondary={`${data.max_altitude_m} m at ${data.max_altitude_time_s}s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Min Flight Altitude" 
                                secondary={`${data.min_altitude_flight_m} m at ${data.min_altitude_flight_time_s}s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Max Distance from Launch" 
                                secondary={`${data.max_distance_from_launch_m} m at ${data.max_distance_time_s}s`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            <ListItem sx={{ px: 0, py: 0.5 }}>
                              <ListItemText 
                                primary="Flight Duration" 
                                secondary={`${data.duration_s}s (${(data.duration_s / 60).toFixed(1)}min)`}
                                primaryTypographyProps={{ variant: 'caption' }}
                                secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                              />
                            </ListItem>
                            {velocityData && (
                              <>
                                <ListItem sx={{ px: 0, py: 0.5 }}>
                                  <ListItemText 
                                    primary="Max Speed" 
                                    secondary={`${velocityData.max_velocity_ms} m/s`}
                                    primaryTypographyProps={{ variant: 'caption' }}
                                    secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                                  />
                                </ListItem>
                                <ListItem sx={{ px: 0, py: 0.5 }}>
                                  <ListItemText 
                                    primary="Avg Speed" 
                                    secondary={`${velocityData.avg_velocity_ms} m/s`}
                                    primaryTypographyProps={{ variant: 'caption' }}
                                    secondaryTypographyProps={{ variant: 'body2', fontWeight: 'medium' }}
                                  />
                                </ListItem>
                              </>
                            )}
                          </List>
                        </Paper>
                      </Grid>
                      );
                    })}
                  </Grid>
                )}
              </Paper>
            </Collapse>
          </Box>
          
          <Grid container spacing={3}>
            {/* Safety Analysis */}
            {safety_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={technicalPanelSx}>
                  <Typography variant="h6" gutterBottom sx={analysisHeadingSx}>
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
                        secondary={
                          safety_metrics.collision_warnings_count > 0 && comprehensiveMetrics?.safety_metrics?.collision_warnings?.length > 0
                            ? `${safety_metrics.collision_warnings_count} detected - Most critical: Drones ${comprehensiveMetrics.safety_metrics.collision_warnings[0].drone_1}-${comprehensiveMetrics.safety_metrics.collision_warnings[0].drone_2} (${comprehensiveMetrics.safety_metrics.collision_warnings[0].distance}m)`
                            : `${safety_metrics.collision_warnings_count || 0} detected`
                        }
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
                <Paper sx={technicalPanelSx}>
                  <Typography variant="h6" gutterBottom sx={analysisHeadingSx}>
                    <SpeedIcon />
                    Performance Analysis
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Velocity" 
                        secondary={
                          performance_metrics.max_velocity_details 
                            ? `${performance_metrics.max_velocity_ms} m/s (${performance_metrics.max_velocity_kmh} km/h) - Drone ${performance_metrics.max_velocity_details.drone_id} at ${performance_metrics.max_velocity_details.time_s}s`
                            : `${performance_metrics.max_velocity_ms} m/s (${performance_metrics.max_velocity_kmh} km/h)`
                        }
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Acceleration" 
                        secondary={
                          performance_metrics.max_acceleration_details 
                            ? `${performance_metrics.max_acceleration_ms2} m/s² - Drone ${performance_metrics.max_acceleration_details.drone_id} at ${performance_metrics.max_acceleration_details.time_s}s`
                            : `${performance_metrics.max_acceleration_ms2} m/s²`
                        }
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

            {/* Enhanced Basic Metrics */}
            {comprehensiveMetrics?.basic_metrics && (
              <Grid item xs={12} lg={6}>
                <Paper sx={technicalPanelSx}>
                  <Typography variant="h6" gutterBottom sx={analysisHeadingSx}>
                    <AssessmentIcon />
                    Enhanced Metrics
                  </Typography>
                  <List dense>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Altitude" 
                        secondary={
                          comprehensiveMetrics.basic_metrics.max_altitude_details 
                            ? `${comprehensiveMetrics.basic_metrics.max_altitude_details.value} m - Drone ${comprehensiveMetrics.basic_metrics.max_altitude_details.drone_id} at ${comprehensiveMetrics.basic_metrics.max_altitude_details.time_s}s`
                            : `${comprehensiveMetrics.basic_metrics.max_altitude_m || 'N/A'} m`
                        }
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Min Altitude (Flight)" 
                        secondary={
                          comprehensiveMetrics.basic_metrics.min_altitude_details 
                            ? `${comprehensiveMetrics.basic_metrics.min_altitude_details.value} m - Drone ${comprehensiveMetrics.basic_metrics.min_altitude_details.drone_id} at ${comprehensiveMetrics.basic_metrics.min_altitude_details.time_s}s`
                            : `${comprehensiveMetrics.basic_metrics.min_altitude_flight_m || 'N/A'} m`
                        }
                        primaryTypographyProps={{ fontWeight: 'medium' }}
                      />
                    </ListItem>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText 
                        primary="Max Distance from Launch" 
                        secondary={
                          comprehensiveMetrics.basic_metrics.max_distance_details 
                            ? `${comprehensiveMetrics.basic_metrics.max_distance_details.value} m - Drone ${comprehensiveMetrics.basic_metrics.max_distance_details.drone_id} at ${comprehensiveMetrics.basic_metrics.max_distance_details.time_s}s`
                            : `${comprehensiveMetrics.basic_metrics.max_distance_from_launch_m || 'N/A'} m`
                        }
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
                <Paper sx={technicalPanelSx}>
                  <Typography variant="h6" gutterBottom sx={analysisHeadingSx}>
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
      <Typography variant="h5" sx={{ color: VIS_TOKENS.primary, mb: 1 }}>
        Drone Show Visualization
      </Typography>

      {!loading && !hasImportedShow && !error && (
        <Alert severity="info" sx={{ mb: 3 }}>
          No processed Drone Show is active yet. Upload a SkyBrush ZIP above to populate plots,
          metrics, and launch-ready trajectory data.
        </Alert>
      )}
      
      {/* Show File Information */}
      {comprehensiveMetrics?.show_info && (
        <Box className="upload-info-box" sx={{ borderRadius: 1, p: 2, mb: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
            <Box>
              <Typography variant="subtitle2" className="upload-info-title">
                📁 Current Show: {comprehensiveMetrics.show_info.filename}
              </Typography>
              <Typography variant="caption" className="upload-info-subtitle">
                Uploaded: {new Date(comprehensiveMetrics.show_info.uploaded_at).toLocaleString()}
              </Typography>
            </Box>
            <Box sx={{ textAlign: 'right' }}>
              <Typography variant="caption" className="upload-info-subtitle">
                Processed: {new Date(comprehensiveMetrics.show_info.processed_at).toLocaleString()}
              </Typography>
            </Box>
          </Box>
        </Box>
      )}

      {/* Essential Metrics - Always Visible - 3 cards per row on large screens */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <AccessTimeIcon className="metric-icon primary" sx={{ fontSize: 48, mb: 2 }} />
              <Typography variant="subtitle1" className="metric-label" gutterBottom>
                Duration
              </Typography>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {formatDuration()}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <TheatersIcon className="metric-icon secondary" sx={{ fontSize: 48, mb: 2 }} />
              <Typography variant="subtitle1" className="metric-label" gutterBottom>
                Drone Count
              </Typography>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {showDetails.droneCount || 'N/A'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <HeightIcon className="metric-icon success" sx={{ fontSize: 48, mb: 2 }} />
              <Tooltip title="Maximum altitude reached during the entire show">
                <Typography variant="subtitle1" className="metric-label" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Altitude <HelpIcon sx={{ fontSize: 18 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {formatMaxAltitude()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.max_altitude_details && (
                <Typography variant="caption" className="metric-detail" sx={{ display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.max_altitude_details.drone_id} at {comprehensiveMetrics.basic_metrics.max_altitude_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <HeightIcon className="metric-icon warning" sx={{ fontSize: 48, mb: 2, transform: 'rotate(180deg)' }} />
              <Tooltip title="Minimum altitude during flight phase (excluding takeoff/landing within 20m)">
                <Typography variant="subtitle1" className="metric-label" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Min Altitude <HelpIcon sx={{ fontSize: 18 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {formatMinAltitude()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.min_altitude_details && (
                <Typography variant="caption" className="metric-detail" sx={{ display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.min_altitude_details.drone_id} at {comprehensiveMetrics.basic_metrics.min_altitude_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <SpeedIcon className="metric-icon info" sx={{ fontSize: 48, mb: 2 }} />
              <Tooltip title="Maximum velocity reached by any drone during the show">
                <Typography variant="subtitle1" className="metric-label" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Speed <HelpIcon sx={{ fontSize: 18 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {formatMaxSpeed()}
              </Typography>
              {comprehensiveMetrics?.performance_metrics?.max_velocity_details && (
                <Typography variant="caption" className="metric-detail" sx={{ display: 'block' }}>
                  Drone {comprehensiveMetrics.performance_metrics.max_velocity_details.drone_id} at {comprehensiveMetrics.performance_metrics.max_velocity_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} lg={4}>
          <Card variant="outlined" className="metric-card" sx={{ height: '100%', borderRadius: 2, transition: 'all 0.3s ease' }}>
            <CardContent sx={{ textAlign: 'center', py: 3 }}>
              <TimelineIcon className="metric-icon secondary" sx={{ fontSize: 48, mb: 2 }} />
              <Tooltip title="Maximum 3D distance any drone traveled from its launch position during the show">
                <Typography variant="subtitle1" className="metric-label" gutterBottom sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                  Max Distance <HelpIcon sx={{ fontSize: 18 }} />
                </Typography>
              </Tooltip>
              <Typography variant="h4" className="metric-value" sx={{ mb: 1 }}>
                {formatMaxDistance()}
              </Typography>
              {comprehensiveMetrics?.basic_metrics?.max_distance_details && (
                <Typography variant="caption" className="metric-detail" sx={{ display: 'block' }}>
                  Drone {comprehensiveMetrics.basic_metrics.max_distance_details.drone_id} at {comprehensiveMetrics.basic_metrics.max_distance_details.time_s}s
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Advanced Safety Metrics Row - 2 cards per row */}
      {comprehensiveMetrics && comprehensiveMetrics.safety_metrics && (
        <Grid container spacing={3} sx={{ mb: 4 }}>
          <Grid item xs={12} md={6}>
            <Card variant="outlined" sx={{ 
              height: '100%', 
              bgcolor: VIS_TOKENS.surface,
              borderRadius: 2,
              transition: 'all 0.3s ease',
              '&:hover': { boxShadow: 'var(--shadow-md)' }
            }}>
              <CardContent sx={{ textAlign: 'center', py: 3 }}>
                <SecurityIcon color="success" sx={{ fontSize: 40, mb: 2 }} />
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, justifyContent: 'center', mb: 2 }}>
                  <Typography variant="subtitle1" color="textSecondary" sx={{ fontWeight: 600 }}>
                    Min Proximity
                  </Typography>
                  <Tooltip title="Minimum separation distance between any two drones during the entire show. Safe operation requires >2m separation." arrow>
                    <HelpIcon sx={{ fontSize: 16, color: VIS_TOKENS.textSecondary }} />
                  </Tooltip>
                </Box>
                <Typography variant="h4" sx={{ fontWeight: 'bold', color: VIS_TOKENS.primary }}>
                  {typeof comprehensiveMetrics.safety_metrics.min_inter_drone_distance_m === 'number' 
                    ? `${comprehensiveMetrics.safety_metrics.min_inter_drone_distance_m} m` 
                    : 'N/A'}
                </Typography>
                {comprehensiveMetrics?.safety_metrics?.min_distance_details && (
                  <Typography variant="body2" color="textSecondary" sx={{ mt: 1, fontWeight: 500 }}>
                    Drones {comprehensiveMetrics.safety_metrics.min_distance_details.drone_1} & {comprehensiveMetrics.safety_metrics.min_distance_details.drone_2} at {comprehensiveMetrics.safety_metrics.min_distance_details.time_s}s
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={6}>
            <Card variant="outlined" sx={{ 
              height: '100%', 
              bgcolor: VIS_TOKENS.surface,
              borderRadius: 2,
              transition: 'all 0.3s ease',
              border: comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' 
                ? `2px solid ${VIS_TOKENS.success}`
                : comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION'
                ? `2px solid ${VIS_TOKENS.warning}`
                : `2px solid ${VIS_TOKENS.border}`,
              '&:hover': { boxShadow: 'var(--shadow-md)' }
            }}>
              <CardContent sx={{ textAlign: 'center', py: 3 }}>
                <SecurityIcon 
                  sx={{ 
                    fontSize: 40, 
                    mb: 2,
                    color: comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' 
                      ? VIS_TOKENS.success
                      : comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION'
                      ? VIS_TOKENS.warning
                      : VIS_TOKENS.textSecondary
                  }} 
                />
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5, mb: 2 }}>
                  <Typography variant="subtitle1" color="textSecondary" sx={{ fontWeight: 600 }}>
                    Safety Status
                  </Typography>
                  <Tooltip 
                    title={
                      comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION' 
                        ? `⚠️ CAUTION: ${comprehensiveMetrics.safety_metrics.collision_warnings_count || 0} collision warnings detected.${comprehensiveMetrics?.safety_metrics?.collision_warnings?.length > 0 ? ` Critical proximities: ${comprehensiveMetrics.safety_metrics.collision_warnings.slice(0, 3).map(w => `Drones ${w.drone_1}-${w.drone_2} (${w.distance}m at ${w.time}s)`).join(', ')}${comprehensiveMetrics.safety_metrics.collision_warnings.length > 3 ? '...' : ''}` : ''} Check inter-drone distances and flight paths before launch.`
                        : comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE'
                        ? '✅ SAFE: No collision risks detected. All clearances maintained properly.'
                        : 'Safety assessment based on collision risk analysis, ground clearance, and inter-drone distances.'
                    }
                    arrow
                  >
                    <HelpIcon sx={{ fontSize: 16, color: VIS_TOKENS.textSecondary }} />
                  </Tooltip>
                </Box>
                <Chip 
                  label={comprehensiveMetrics?.safety_metrics?.safety_status || 'Analyzing...'} 
                  color={
                    comprehensiveMetrics?.safety_metrics?.safety_status === 'SAFE' ? 'success' :
                    comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION' ? 'warning' : 'default'
                  }
                  sx={{ fontWeight: 'bold', fontSize: '1rem', px: 2, py: 1 }}
                />
                {comprehensiveMetrics?.safety_metrics?.safety_status === 'CAUTION' && (
                  <Typography variant="caption" color="warning.main" sx={{ display: 'block', mt: 1, fontSize: '0.8rem', fontWeight: 500 }}>
                    Review flight paths before launch
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {loading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, p: 2, bgcolor: VIS_TOKENS.surface, borderRadius: 1 }}>
          <CircularProgress size={20} color="primary" />
          <Typography variant="body2" color="primary" sx={{ fontWeight: 'medium' }}>
            Loading drone show analysis...
          </Typography>
        </Box>
      )}
      {error && (
        <Typography variant="body1" color="error" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}

      {/* Combined Plot - All Drones Together */}
      {plots.some(name => name === 'combined_drone_paths.jpg') && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ ...analysisHeadingSx, mb: 2 }}>
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
                src={buildShowPlotUrl('combined_drone_paths.jpg')}
                alt="All Drones Combined Trajectory" 
                style={{ 
                  ...plotImageStyle,
                  maxWidth: '800px',
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
          <Typography variant="h6" sx={{ ...analysisHeadingSx, mb: 2 }}>
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
                const plotUrl = buildShowPlotUrl(plot);
                const droneId = plot.match(/drone_(\d+)_path/)?.[1] || index + 1;
                return (
                  <Paper key={`individual-${index}`} sx={{ p: 1 }}>
                    <Typography variant="subtitle2" sx={{ mb: 1, textAlign: 'center', color: VIS_TOKENS.primary }}>
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
                          ...plotImageStyle,
                          borderRadius: '6px',
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
          bgcolor: VIS_TOKENS.overlay,
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
              bgcolor: VIS_TOKENS.surface,
              color: VIS_TOKENS.text,
              zIndex: 'var(--z-modal)',
              '&:hover': { bgcolor: VIS_TOKENS.surfaceRaised }
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
                  bgcolor: VIS_TOKENS.surface,
                  color: VIS_TOKENS.text,
                  fontSize: '20px',
                  zIndex: 'var(--z-modal)',
                  '&:hover': { bgcolor: VIS_TOKENS.surfaceRaised }
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
                  bgcolor: VIS_TOKENS.surface,
                  color: VIS_TOKENS.text,
                  fontSize: '20px',
                  zIndex: 'var(--z-modal)',
                  '&:hover': { bgcolor: VIS_TOKENS.surfaceRaised }
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
            bgcolor: VIS_TOKENS.surface,
            borderRadius: 2,
            overflow: 'hidden',
            boxShadow: 'var(--shadow-lg)'
          }}>
            {plots.length > 0 && (
              <>
                <img
                  src={buildShowPlotUrl(plots[currentIndex] || '')}
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
                <Box sx={{ p: 2, bgcolor: VIS_TOKENS.surface, width: '100%', textAlign: 'center' }}>
                  <Typography variant="subtitle1" sx={{ color: VIS_TOKENS.primary, fontWeight: 'bold' }}>
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
