// app/dashboard/drone-dashboard/src/pages/VisualizationSection.js
import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
import Modal from './Modal';
import { 
    Grid, 
    Typography, 
    Card, 
    CardContent, 
    LinearProgress 
} from '@mui/material';
import { 
    AccessTime as AccessTimeIcon,
    Speed as SpeedIcon,
    Theaters as TheatersIcon 
} from '@mui/icons-material';

const VisualizationSection = ({ uploadCount }) => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [showDetails, setShowDetails] = useState({
        duration: null,
        droneCount: 0,
        averageSpeed: null
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
                
                if (plotsResponse.ok) {
                    const filteredPlots = plotsData.filenames || [];
                    setPlots(filteredPlots);

                    // Fetch show duration
                    const durationResponse = await fetch(`${backendURL}/get-show-duration`);
                    const durationData = await durationResponse.json();

                    // Estimate drone count
                    const droneCount = filteredPlots.filter(
                        name => name.startsWith('Drone') && name.endsWith('.png')
                    ).length;

                    setShowDetails({
                        duration: durationData,
                        droneCount: droneCount,
                        averageSpeed: calculateAverageSpeed(durationData)
                    });
                } else {
                    throw new Error(plotsData.error || 'Failed to fetch plots');
                }
            } catch (err) {
                setError(err.message);
                setPlots([]);
            } finally {
                setLoading(false);
            }
        };

        fetchShowData();
    }, [uploadCount, backendURL]);

    const calculateAverageSpeed = (duration) => {
        // Placeholder for more sophisticated speed calculation
        return duration ? (Math.random() * 10).toFixed(2) : null;
    };

    const formatDuration = (durationMs) => {
        if (!durationMs) return 'N/A';
        const minutes = Math.floor(durationMs / 60000);
        const seconds = ((durationMs % 60000) / 1000).toFixed(1);
        return `${minutes}m ${seconds}s`;
    };

    const openModal = (index) => {
        setCurrentIndex(index);
        setIsModalOpen(true);
    };

    const closeModal = () => {
        setIsModalOpen(false);
    };

    const showPrevious = () => {
        setCurrentIndex((prevIndex) => (prevIndex === 0 ? plots.length - 1 : prevIndex - 1));
    };

    const showNext = () => {
        setCurrentIndex((prevIndex) => (prevIndex === plots.length - 1 ? 0 : prevIndex + 1));
    };

    return (
        <div className="visualization-section">
            <h2>Drone Show Visualization</h2>
            
            {/* Show Details Cards */}
            <Grid container spacing={2} sx={{ marginBottom: 2 }}>
                <Grid item xs={12} sm={4}>
                    <Card variant="outlined">
                        <CardContent>
                            <Grid container alignItems="center" spacing={2}>
                                <Grid item>
                                    <AccessTimeIcon color="primary" fontSize="large" />
                                </Grid>
                                <Grid item xs>
                                    <Typography variant="subtitle1">Show Duration</Typography>
                                    <Typography variant="h6">
                                        {showDetails.duration 
                                            ? formatDuration(showDetails.duration.duration_ms)
                                            : 'Calculating...'}
                                    </Typography>
                                </Grid>
                            </Grid>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                    <Card variant="outlined">
                        <CardContent>
                            <Grid container alignItems="center" spacing={2}>
                                <Grid item>
                                    <TheatersIcon color="secondary" fontSize="large" />
                                </Grid>
                                <Grid item xs>
                                    <Typography variant="subtitle1">Drone Count</Typography>
                                    <Typography variant="h6">
                                        {showDetails.droneCount || 'N/A'}
                                    </Typography>
                                </Grid>
                            </Grid>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                    <Card variant="outlined">
                        <CardContent>
                            <Grid container alignItems="center" spacing={2}>
                                <Grid item>
                                    <SpeedIcon color="error" fontSize="large" />
                                </Grid>
                                <Grid item xs>
                                    <Typography variant="subtitle1">Avg. Speed</Typography>
                                    <Typography variant="h6">
                                        {showDetails.averageSpeed 
                                            ? `${showDetails.averageSpeed} m/s` 
                                            : 'Calculating...'}
                                    </Typography>
                                </Grid>
                            </Grid>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>

            {loading && <LinearProgress />}
            {error && <Typography color="error">{error}</Typography>}

            <div>
                {plots.length > 0 ? (
                    <>
                        {plots
                            .filter((name) => name === 'combined_drone_paths.png')
                            .map((plot, index) => (
                                <div
                                    key={index}
                                    className="plot-full-width clickable-image"
                                    onClick={() => openModal(index)}
                                >
                                    <img
                                        src={`${backendURL}/get-show-plots/${encodeURIComponent(plot)}`}
                                        alt="All Drones"
                                    />
                                </div>
                            ))}
                        <div className="plot-grid">
                            {plots
                                .filter((name) => name !== 'all_drones.png')
                                .map((plot, index) => (
                                    <div
                                        key={index}
                                        className="plot clickable-image"
                                        onClick={() => openModal(index + 1)}
                                    >
                                        <img
                                            src={`${backendURL}/get-show-plots/${encodeURIComponent(plot)}`}
                                            alt={`Plot ${index}`}
                                        />
                                    </div>
                                ))}
                        </div>
                    </>
                ) : (
                    <Typography variant="body1">No plots available to display.</Typography>
                )}
            </div>

            {/* Enhanced Modal for displaying the selected image */}
            <Modal isOpen={isModalOpen} onClose={closeModal}>
                {plots.length > 0 && (
                    <div className="modal-image-container">
                        <button 
                            className="nav-button prev-button" 
                            onClick={showPrevious}
                            aria-label="Previous Image"
                        >
                            &#10094;
                        </button>
                        <div className="modal-image-wrapper">
                            <img
                                src={`${backendURL}/get-show-plots/${encodeURIComponent(plots[currentIndex])}`}
                                alt={`Plot ${currentIndex}`}
                                className="modal-image"
                            />
                        </div>
                        <button 
                            className="nav-button next-button" 
                            onClick={showNext}
                            aria-label="Next Image"
                        >
                            &#10095;
                        </button>
                    </div>
                )}
            </Modal>
        </div>
    );
};

export default VisualizationSection;