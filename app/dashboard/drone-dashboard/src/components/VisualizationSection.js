import React, { useState, useEffect } from 'react';
import { getBackendURL } from '../utilities/utilities'; // Ensure this utility function correctly returns the backend URL

const VisualizationSection = ({ uploadCount }) => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        const fetchPlots = async () => {
            setLoading(true);
            setError('');
            try {
                const response = await fetch(`${getBackendURL()}/get-show-plots`);
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
    }, [uploadCount]); // Dependency on uploadCount to refetch when new uploads happen

    return (
        <div className="visualization-section">
            <h2>Visualization of Drone Paths</h2>
            {loading && <p>Loading plots...</p>}
            {error && <p className="error">Error: {error}</p>}
            <div className="plot-container">
                {plots.length > 0 ? (
                    <>
                        {plots.filter(name => name === "all_drones.png").map((plot, index) => (
                            <div key={index} className="plot-full-width">
                                <img src={`${getBackendURL()}/get-show-plots/${encodeURIComponent(plot)}`} alt="All Drones" />
                            </div>
                        ))}
                        <div className="plot-grid">
                            {plots.filter(name => name !== "all_drones.png").map((plot, index) => (
                                <div key={index} className="plot">
                                    <img src={`${getBackendURL()}/get-show-plots/${encodeURIComponent(plot)}`} alt={`Plot ${index}`} />
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <p>No plots available to display.</p>
                )}
            </div>
        </div>
    );
};

export default VisualizationSection;
