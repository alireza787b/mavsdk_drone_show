// src/pages/ManageDroneShow.js

import React, { useState } from 'react';
import ImportSection from './ImportSection';
import ExportSection from './ExportSection';
import VisualizationSection from './VisualizationSection';
import '../styles/ManageDroneShow.css';
import { ToastContainer } from 'react-toastify'; // Import ToastContainer

const ManageDroneShow = () => {
    const [uploadCount, setUploadCount] = useState(0);

    return (
        <div className="manage-drone-show-container">
            <h1>Manage Drone Show</h1>
            <ToastContainer /> {/* Add this line */}
            <ImportSection setUploadCount={setUploadCount} />
            <ExportSection />
            <VisualizationSection uploadCount={uploadCount} />
        </div>
    );
};

export default ManageDroneShow;
