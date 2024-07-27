// src/components/ImportSection.js
import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities'; // Ensure this utility is correctly imported

const ImportSection = ({ setUploadCount, setResponseMessage }) => {
    const [selectedFile, setSelectedFile] = useState(null);

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
    };

    const uploadFile = async () => {
        if (!selectedFile) {
            setResponseMessage('Please select a file to upload.');
            return;
        }
        const formData = new FormData();
        formData.append('file', selectedFile);

        try {
            const response = await fetch(`${getBackendURL()}/import-show`, {
                method: 'POST',
                body: formData,
            });
            const result = await response.json();
            if (result.success) {
                setResponseMessage('File uploaded successfully. Processing...');
                setUploadCount(prev => prev + 1);  // Increment to trigger re-fetching plots
            } else {
                setResponseMessage(`Upload failed: ${result.error}`);
            }
        } catch (error) {
            console.error('Upload failed:', error);
            setResponseMessage('Network error. Please try again.');
        }
    };

    return (
        <div className="import-section">
            <h2>Import Drone Show</h2>
            <input type="file" accept=".zip" onChange={handleFileChange} />
            {selectedFile && <p>File selected: {selectedFile.name}</p>}
            <button onClick={uploadFile} disabled={!selectedFile}>Upload</button>
        </div>
    );
};

export default ImportSection;
