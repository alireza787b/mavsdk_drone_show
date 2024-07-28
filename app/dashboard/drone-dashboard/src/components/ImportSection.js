import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities'; // Ensure this utility is correctly implemented
import './ImportSection.css'; // Assuming you have some basic styling and animations defined here

const ImportSection = ({ setUploadCount, setResponseMessage }) => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [uploadError, setUploadError] = useState('');

    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) {
            setResponseMessage('No file selected. Please choose a file.');
            return;
        }
        if (!file.name.endsWith('.zip')) {
            setResponseMessage('Invalid file type. Please select a ZIP file.');
            return;
        }
        setSelectedFile(file);
        setResponseMessage('');
        setUploadError('');
        setUploadProgress(0);
    };

    const uploadFile = async () => {
        if (!selectedFile) {
            setResponseMessage('Please select a file to upload.');
            return;
        }
        setIsUploading(true);
        const formData = new FormData();
        formData.append('file', selectedFile);

        try {
            const response = await fetch(`${getBackendURL()}/import-show`, {
                method: 'POST',
                body: formData,
            }, {
                onUploadProgress: progressEvent => {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    setUploadProgress(percentCompleted);
                }
            });

            if (!response.ok) {
                throw new Error('Network response was not ok.');
            }

            const result = await response.json();
            if (result.success) {
                setResponseMessage('File uploaded and processed successfully!');
                setUploadCount(prev => prev + 1); // Increment to trigger re-fetching plots
                setIsUploading(false);
            } else {
                throw new Error(result.error || 'Unknown error during file upload.');
            }
        } catch (error) {
            console.error('Upload failed:', error);
            setResponseMessage('Upload failed: ' + error.message);
            setUploadError(error.message);
            setIsUploading(false);
        }
    };

    return (
        <div className="import-section">
            <h2>Import Drone Show</h2>
            <input type="file" accept=".zip" onChange={handleFileChange} />
            {selectedFile && <p>File selected: {selectedFile.name}</p>}
            <button onClick={uploadFile} disabled={!selectedFile || isUploading}>Upload</button>
            {isUploading && (
                <div>
                    <p>Uploading... {uploadProgress}%</p>
                    <div className="progress-bar">
                        <div className="progress-bar-fill" style={{ width: `${uploadProgress}%` }}></div>
                    </div>
                </div>
            )}
            {uploadError && <p className="error-message">{uploadError}</p>}
        </div>
    );
};

export default ImportSection;
