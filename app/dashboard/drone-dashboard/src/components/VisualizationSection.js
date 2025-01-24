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
    Theaters as TheatersIcon 
} from '@mui/icons-material';

const VisualizationSection = ({ uploadCount }) => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [showDetails, setShowDetails] = useState({
        droneCount: 0,
        duration: null
    });

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    console.log(`Backend URL: ${backendURL}`); // Log backend URL for debugging

    useEffect(() => {
        const fetchShowData = async () => {
            setLoading(true);
            setError('');
            try {
                // Fetch plots
                console.log('Fetching plots...');
                const plotsResponse = await fetch(`${backendURL}/get-show-plots`);
                const plotsData = await plotsResponse.json();
                console.log('Plots Response:', plotsData);

                if (plotsResponse.ok) {
                    const filenames = plotsData.filenames || [];
                    setPlots(filenames);
                    console.log('Filtered Plots:', filenames);

                    // Fetch show info
                    console.log('Fetching show info...');
                    const showInfoResponse = await fetch(`${backendURL}/get-show-info`);
                    const showInfoData = await showInfoResponse.json();
                    console.log('Show Info Response:', showInfoData);

                    setShowDetails({
                        droneCount: showInfoData.drone_count,
                        duration: {
                            ms: showInfoData.duration_ms,
                            minutes: parseInt(showInfoData.duration_minutes),
                            seconds: parseInt(showInfoData.duration_seconds)
                        }
                    });
                } else {
                    throw new Error(plotsData.error || 'Failed to fetch plots');
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

    const formatDuration = () => {
        const { duration } = showDetails;
        if (!duration) return 'N/A';
        return `${duration.minutes}m ${duration.seconds.toFixed(1)}s`;
    };

    const openModal = (index) => {
        console.log(`Opening modal for index: ${index}`);
        setCurrentIndex(index);
        setIsModalOpen(true);
    };

    const closeModal = () => {
        console.log('Closing modal...');
        setIsModalOpen(false);
    };

    const showPrevious = () => {
        const previousIndex = currentIndex === 0 ? plots.length - 1 : currentIndex - 1;
        console.log(`Showing previous image. Current Index: ${currentIndex}, New Index: ${previousIndex}`);
        setCurrentIndex(previousIndex);
    };

    const showNext = () => {
        const nextIndex = currentIndex === plots.length - 1 ? 0 : currentIndex + 1;
        console.log(`Showing next image. Current Index: ${currentIndex}, New Index: ${nextIndex}`);
        setCurrentIndex(nextIndex);
    };

    return (
        <div className="visualization-section">
            <h2>Drone Show Visualization</h2>
            
            {/* Show Details Cards */}
            <Grid container spacing={2} sx={{ marginBottom: 2 }}>
                <Grid item xs={12} sm={6}>
                    <Card variant="outlined">
                        <CardContent>
                            <Grid container alignItems="center" spacing={2}>
                                <Grid item>
                                    <AccessTimeIcon color="primary" fontSize="large" />
                                </Grid>
                                <Grid item xs>
                                    <Typography variant="subtitle1">Show Duration</Typography>
                                    <Typography variant="h6">
                                        {formatDuration()}
                                    </Typography>
                                </Grid>
                            </Grid>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid item xs={12} sm={6}>
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
            </Grid>

            {loading && <LinearProgress />}
            {error && <Typography color="error">{error}</Typography>}

            <div>
                {/* Combined Plot */}
                {plots
                    .filter((name) => name === 'combined_drone_paths.png')
                    .map((plot, index) => {
                        const plotUrl = `${backendURL}/get-show-plots/${encodeURIComponent(plot)}`;
                        console.log('Combined Plot URL:', plotUrl);
                        return (
                            <div
                                key={`combined-${index}`}
                                className="plot-full-width clickable-image"
                                onClick={() => openModal(0)} // First modal index
                            >
                                <img
                                    src={plotUrl}
                                    alt="All Drones"
                                    style={{ width: '100%' }}
                                />
                            </div>
                        );
                    })}

                {/* Individual Plots */}
                <div className="plot-grid">
                    {plots
                        .filter((name) => name !== 'combined_drone_paths.png')
                        .map((plot, index) => {
                            const plotUrl = `${backendURL}/get-show-plots/${encodeURIComponent(plot)}`;
                            console.log(`Individual Plot URL (index ${index + 1}):`, plotUrl);
                            return (
                                <div
                                    key={`individual-${index}`}
                                    className="plot clickable-image"
                                    onClick={() => openModal(index + 1)} // Offset index by 1 for modal
                                >
                                    <img
                                        src={plotUrl}
                                        alt={`Plot ${index}`}
                                        style={{ width: '100%' }}
                                    />
                                </div>
                            );
                        })}
                </div>
            </div>

            {/* Modal for displaying the selected image */}
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
