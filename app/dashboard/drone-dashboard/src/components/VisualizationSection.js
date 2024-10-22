// app/dashboard/drone-dashboard/src/pages/VisualizationSection.js

import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
import Modal from './Modal'; // Import the custom Modal component

const VisualizationSection = ({ uploadCount }) => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [currentIndex, setCurrentIndex] = useState(0);

    // Define the backend URL once at the start
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    useEffect(() => {
        const fetchPlots = async () => {
            setLoading(true);
            setError('');
            try {
                console.log(`Fetching plot list from URL: ${backendURL}/get-show-plots`);
                const response = await fetch(`${backendURL}/get-show-plots`);
                const data = await response.json();
                if (response.ok) {
                    setPlots(data.filenames || []);
                } else {
                    throw new Error(data.error || 'Failed to fetch plots');
                }
            } catch (err) {
                setError(err.message);
                setPlots([]);
            } finally {
                setLoading(false);
            }
        };

        fetchPlots();
    }, [uploadCount, backendURL]);

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
            <h2>Visualization of Drone Paths</h2>
            {loading && <p>Loading plots...</p>}
            {error && <p className="error">Error: {error}</p>}
            <div>
                {plots.length > 0 ? (
                    <>
                        {plots
                            .filter((name) => name === 'all_drones.png')
                            .map((plot, index) => (
                                <div
                                    key={index}
                                    className="plot-full-width"
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
                                        className="plot"
                                        onClick={() => openModal(index + 1)} // +1 to account for the first full-width image
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
                    <p>No plots available to display.</p>
                )}
            </div>

            {/* Modal for displaying the selected image */}
            <Modal isOpen={isModalOpen} onClose={closeModal}>
                {plots.length > 0 && (
                    <div className="modal-image-container">
                        <button className="nav-button prev-button" onClick={showPrevious}>
                            &#10094; {/* Left Arrow */}
                        </button>
                        <img
                            src={`${backendURL}/get-show-plots/${encodeURIComponent(plots[currentIndex])}`}
                            alt={`Plot ${currentIndex}`}
                            className="modal-image"
                        />
                        <button className="nav-button next-button" onClick={showNext}>
                            &#10095; {/* Right Arrow */}
                        </button>
                    </div>
                )}
            </Modal>
        </div>
    );
};

export default VisualizationSection;
