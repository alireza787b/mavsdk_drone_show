//app/dashboard/drone-dashboard/src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import ImportSection from '../components/ImportSection';
import ExportSection from '../components/ExportSection';
import VisualizationSection from '../components/VisualizationSection';
import '../styles/ManageDroneShow.css'; // Update CSS for new layout

const ManageDroneShow = () => {
    const [uploadCount, setUploadCount] = useState(0);
    const [responseMessage, setResponseMessage] = useState('');

    return (
        <div className="manage-drone-show-container">
            <h1>Manage Drone Show</h1>
            {responseMessage && <div className="response-message">{responseMessage}</div>}
            <ImportSection setUploadCount={setUploadCount} setResponseMessage={setResponseMessage} />
            <ExportSection />
            <VisualizationSection uploadCount={uploadCount} />
        </div>
    );
};

export default ManageDroneShow;
