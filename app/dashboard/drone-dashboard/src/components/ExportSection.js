//app/dashboard/drone-dashboard/src/components/ExportSection.js
import React from 'react';

const ExportSection = () => {
    const handleDownload = (type) => {
        const downloadUrl = `${process.env.REACT_APP_BACKEND_URL}/download-${type}-show`;
        window.open(downloadUrl, '_blank');
    };

    return (
        <div className="export-section">
            <h2>Export Drone Show Data</h2>
            <div className="export-buttons">
                <button onClick={() => handleDownload('raw')}>Download Raw Show</button>
                <button onClick={() => handleDownload('processed')}>Download Processed Show</button>
            </div>
            <p className="info">
                Use the buttons above to download the raw or processed data for your drone shows. 
                Raw data contains the original configurations and settings, while processed data includes adjustments and optimizations made by our system.
            </p>
        </div>
    );
};

export default ExportSection;
