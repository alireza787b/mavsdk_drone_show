// src/pages/ImportSection.js

import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import '../styles/ImportSection.css';
import { CircularProgress } from '@mui/material';

const ImportSection = ({ setUploadCount }) => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [isUploading, setIsUploading] = useState(false);

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) {
            toast.warn('No file selected. Please choose a file.');
            return;
        }
        if (!file.name.endsWith('.zip')) {
            toast.error('Invalid file type. Please select a ZIP file.');
            return;
        }
        setSelectedFile(file);
    };

    const uploadFile = () => {
        if (!selectedFile) {
            toast.warn('Please select a file to upload.');
            return;
        }

        const formData = new FormData();
        formData.append('file', selectedFile);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${getBackendURL()}/import-show`);

        xhr.onload = () => {
            setIsUploading(false);
            if (xhr.status === 200) {
                try {
                    const result = JSON.parse(xhr.responseText);
                    if (result.success) {
                        toast.success('File uploaded and processed successfully!');
                        setUploadCount(prev => prev + 1);
                        setSelectedFile(null);
                    } else {
                        toast.error(result.error || 'Unknown error during file upload.');
                    }
                } catch (error) {
                    console.error('Error parsing response:', error);
                    toast.error('Invalid server response.');
                }
            } else {
                toast.error('Network error. Please try again.');
            }
        };

        xhr.onerror = () => {
            setIsUploading(false);
            toast.error('Network error. Please try again.');
        };

        setIsUploading(true);
        xhr.send(formData);
    };

    return (
        <div className="import-section">
            <h2>Import Drone Show</h2>
            <div className="intro-section">
                <p>Welcome to the Drone Show Import Utility of our Swarm Dashboard. This tool streamlines the entire workflow for your drone shows. Here's what you can do:</p>
                <ul>
                    <li><strong>Upload</strong>:Upload ZIP files exported from SkyBrush with just one click.</li>
                    <li><strong>Process</strong>: Our system automatically processes and adapts these files for compatibility.</li>
                    <li><strong>Visualize</strong>: Generate plots for your drone paths automatically.</li>
                    <li><strong>Update</strong>: Your mission configuration file is auto-updated based on the processed data.</li>
                    <li><strong>Access</strong>: Retrieve processed plot images and CSV files from the <code>shapes/swarm</code> directory.</li>
                </ul>
                <p>
                    SkyBrush is a plugin compatible with Blender and 3D Max, designed for creating drone show animations. Learn how to create stunning animations in our <a href="https://youtu.be/wctmCIzpMpY" target="_blank" rel="noreferrer" className="tutorial-link">YouTube tutorial</a>.
                </p>
                <p>
                    For advanced users needing more control over processing parameters, you can directly execute our <code>process_formation.py</code> Python script. The files will be exported to the <code>shapes/swarm</code> directory.
                </p>
            </div>

            <div className="file-upload">
                <input
                    type="file"
                    accept=".zip"
                    onChange={handleFileChange}
                    id="file-input"
                    style={{ display: 'none' }}
                />
                <label htmlFor="file-input" className="file-input-label">
                    {selectedFile ? selectedFile.name : 'Choose ZIP File'}
                </label>
                <button onClick={uploadFile} disabled={!selectedFile || isUploading}>
                    {isUploading ? (
                        <>
                            <CircularProgress size={20} color="inherit" />
                            Uploading...
                        </>
                    ) : (
                        'Upload'
                    )}
                </button>
            </div>
        </div>
    );

};

export default ImportSection;
