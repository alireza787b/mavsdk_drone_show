import React, { useState, useEffect } from 'react';

const VisualizationSection = () => {
    const [plots, setPlots] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        const fetchPlots = async () => {
            setLoading(true);
            try {
                const response = await fetch(`${process.env.REACT_APP_BACKEND_URL}/get-show-plots`);
                const data = await response.json();
                if (response.ok) {
                    setPlots(data.filenames || []);
                    setError('');
                } else {
                    throw new Error('Failed to fetch plots');
                }
            } catch (err) {
                setError(err.message);
                setPlots([]);
            } finally {
                setLoading(false);
            }
        };

        fetchPlots();
    }, []);

    return (
        <div className="visualization-section">
            <h2>Visualization of Drone Paths</h2>
            {loading && <p>Loading plots...</p>}
            {error && <p className="error">Error: {error}</p>}
            {plots.length > 0 ? (
                plots.map((plot, index) => (
                    <img key={index} src={`${process.env.REACT_APP_BACKEND_URL}/get-show-plots/${encodeURIComponent(plot)}`} alt={`Plot ${index}`} />
                ))
            ) : (
                <p>No plots available to display.</p>
            )}
        </div>
    );
};

export default VisualizationSection;
