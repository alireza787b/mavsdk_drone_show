// app/dashboard/drone-dashboard/src/pages/VisualizationSection.js

import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities';
import Lightbox from 'react-image-lightbox';
import 'react-image-lightbox/style.css'; // Import the CSS for lightbox

const VisualizationSection = ({ uploadCount }) => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [modalIsOpen, setModalIsOpen] = useState(false);
    const [currentImage, setCurrentImage] = useState(null);

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

    const openModal = (image) => {
        setCurrentImage(`${backendURL}/get-show-plots/${encodeURIComponent(image)}`);
        setModalIsOpen(true);
    };

    return (
        <div className="visualization-section">
            <h2>Visualization of Drone Paths</h2>
            {loading && <p>Loading plots...</p>}
            {error && <p className="error">Error: {error}</p>}
            <div>
                {plots.length > 0 ? (
                    <>
                        {plots.filter(name => name === "all_drones.png").map((plot, index) => (
                            <div key={index} className="plot-full-width" onClick={() => openModal(plot)}>
                                <img src={`${backendURL}/get-show-plots/${encodeURIComponent(plot)}`} alt="All Drones" />
                            </div>
                        ))}
                        <div className="plot-grid">
                            {plots.filter(name => name !== "all_drones.png").map((plot, index) => (
                                <div key={index} className="plot" onClick={() => openModal(plot)}>
                                    <img src={`${backendURL}/get-show-plots/${encodeURIComponent(plot)}`} alt={`Plot ${index}`} />
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <p>No plots available to display.</p>
                )}
            </div>
            {modalIsOpen && (
                <Lightbox
                    mainSrc={currentImage}
                    onCloseRequest={() => setModalIsOpen(false)}
                />
            )}
        </div>
    );
};

export default VisualizationSection;
