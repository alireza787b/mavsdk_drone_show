import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities'; // Ensure this utility is correctly implemented

const ImportSection = ({ setUploadCount, setResponseMessage }) => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
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
            });

            if (!response.ok) {
                throw new Error('Network response was not ok.');
            }

            const result = await response.json();
            if (result.success) {
                setResponseMessage('File uploaded successfully. Processing...');
                setUploadCount(prev => prev + 1);  // Increment to trigger re-fetching plots
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
            {isUploading && <p>Uploading...</p>}
            {uploadError && <p className="error-message">{uploadError}</p>}
        </div>
    );
};

export default ImportSection;
