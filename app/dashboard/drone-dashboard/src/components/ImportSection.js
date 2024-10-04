// src/pages/ImportSection.js

import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import '../styles/ImportSection.css';
import { CircularProgress, LinearProgress } from '@mui/material';

const ImportSection = ({ setUploadCount }) => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);

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
        setUploadProgress(0);
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

        xhr.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable) {
                const percentCompleted = Math.round((event.loaded * 100) / event.total);
                setUploadProgress(percentCompleted);
            }
        });

        xhr.addEventListener('readystatechange', () => {
            if (xhr.readyState === XMLHttpRequest.OPENED) {
                setIsUploading(true);
            } else if (xhr.readyState === XMLHttpRequest.DONE) {
                setIsUploading(false);
                if (xhr.status === 200) {
                    const result = JSON.parse(xhr.responseText);
                    if (result.success) {
                        toast.success('File uploaded and processed successfully!');
                        setUploadCount(prev => prev + 1);
                        setSelectedFile(null);
                        setUploadProgress(0);
                    } else {
                        toast.error(result.error || 'Unknown error during file upload.');
                    }
                } else {
                    toast.error('Network error. Please try again.');
                }
            }
        });

        xhr.addEventListener('error', () => {
            setIsUploading(false);
            toast.error('Network error. Please try again.');
        });

        xhr.send(formData);
    };

    return (
        <div className="import-section">
            <h2>Import Drone Show</h2>
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
                            Uploading... {uploadProgress}%
                        </>
                    ) : (
                        'Upload'
                    )}
                </button>
            </div>
            {isUploading && (
                <div className="progress-container">
                    <LinearProgress variant="determinate" value={uploadProgress} />
                    <p>{uploadProgress}%</p>
                </div>
            )}
        </div>
    );
};

export default ImportSection;
