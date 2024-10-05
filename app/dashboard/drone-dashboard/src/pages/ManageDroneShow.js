// src/pages/ManageDroneShow.js

import React, { useState } from 'react';
import ImportSection from '../components/ImportSection';
import ExportSection from '../components/ExportSection';
import VisualizationSection from '../components/VisualizationSection';
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
