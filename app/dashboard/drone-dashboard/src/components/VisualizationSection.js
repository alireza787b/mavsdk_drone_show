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
  Button
} from '@mui/material';
import {
  AccessTime as AccessTimeIcon,
  Theaters as TheatersIcon,
} from '@mui/icons-material';
import HeightIcon from '@mui/icons-material/Height'; // For altitude icon

const VisualizationSection = ({ uploadCount }) => {
  const [plots, setPlots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);

  const [showDetails, setShowDetails] = useState({
    droneCount: 0,
    duration: null,
    maxAltitude: null, // Initialize
  });

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
          maxAltitude: showInfoData.max_altitude, // Store altitude
        });
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
        .filter((name) => name === 'combined_drone_paths.png')
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
          .filter((name) => name !== 'combined_drone_paths.png')
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
    </Box>
  );
};

export default VisualizationSection;
