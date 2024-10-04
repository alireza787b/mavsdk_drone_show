// src/pages/ImportShow.js

import React, { useState, useEffect } from 'react';
import '../styles/ImportShow.css';
import { getBackendURL } from '../utilities/utilities';
import { toast } from 'react-toastify';

// Import MUI components
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  CircularProgress,
  LinearProgress,
} from '@mui/material';

// Import the FileUpload component
import FileUpload from '../components/FileUpload';

const ImportShow = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [plotList, setPlotList] = useState([]);
  const [uploadTime, setUploadTime] = useState('N/A');
  const [uploadCount, setUploadCount] = useState(0);
  const [dronesMismatchWarning, setDronesMismatchWarning] = useState(null);
  const [coordinateWarnings, setCoordinateWarnings] = useState([]);
  const [returnWarnings, setReturnWarnings] = useState([]);
  const [openConfirmDialog, setOpenConfirmDialog] = useState(false);
  const [loading, setLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

  // Fetch plot list from backend
  useEffect(() => {
    const fetchPlots = async () => {
      console.log(`Fetching plot list from URL: ${backendURL}/get-show-plots`);

      try {
        const response = await fetch(`${backendURL}/get-show-plots`);
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const data = await response.json();
        setPlotList(data.filenames || []);
        setUploadTime(data.uploadTime || 'N/A');
        console.log('Fetched plot list:', data.filenames);
      } catch (error) {
        console.error('Fetch plots failed:', error);
        toast.error('Error fetching plot list.');
      }
    };

    fetchPlots();
  }, [backendURL, uploadCount]);

  // Check for drone mismatches after plot list updates
  useEffect(() => {
    const checkDronesMismatch = async () => {
      console.log(`Checking drone mismatches at URL: ${backendURL}/get-config-data`);

      try {
        const configResponse = await fetch(`${backendURL}/get-config-data`);
        if (!configResponse.ok) throw new Error(`HTTP error! Status: ${configResponse.status}`);
        const configData = await configResponse.json();

        const configMap = configData.reduce((acc, drone) => {
          acc[drone.hw_id] = { x: parseFloat(drone.x), y: parseFloat(drone.y) };
          return acc;
        }, {});

        const coordinateWarnings = [];
        const returnWarnings = [];
        let droneCountWarning = null;

        if (configData.length !== plotList.length - 1) {
          droneCountWarning = `The number of drones in the uploaded show (${plotList.length - 1}) does not match the number in the config file (${configData.length}).`;
        }

        // For each drone, check for coordinate mismatches
        for (const [hw_id, { x: configX, y: configY }] of Object.entries(configMap)) {
          try {
            const rowResponse = await fetch(`${backendURL}/get-first-last-row/${hw_id}`);
            if (!rowResponse.ok) throw new Error(`HTTP error! Status: ${rowResponse.status}`);
            const rowData = await rowResponse.json();

            const firstRowX = parseFloat(rowData.firstRow.x);
            const firstRowY = parseFloat(rowData.firstRow.y);
            const lastRowX = parseFloat(rowData.lastRow.x);
            const lastRowY = parseFloat(rowData.lastRow.y);

            if (configX !== firstRowX || configY !== firstRowY) {
              coordinateWarnings.push(
                `Drone ${hw_id} has mismatch in initial launch point. Config: (${configX}, ${configY}), CSV: (${firstRowX}, ${firstRowY})`
              );
            }

            if (firstRowX !== lastRowX || firstRowY !== lastRowY) {
              returnWarnings.push(
                `Drone ${hw_id} has different return point. Start: (${firstRowX}, ${firstRowY}), End: (${lastRowX}, ${lastRowY})`
              );
            }
          } catch (error) {
            console.warn(`Could not fetch data for drone ${hw_id}. Skipping...`, error);
          }
        }

        setCoordinateWarnings(coordinateWarnings);
        setReturnWarnings(returnWarnings);
        setDronesMismatchWarning(droneCountWarning);
      } catch (error) {
        console.error('Error checking drone mismatches:', error);
        toast.error('Error checking drone mismatches.');
      }
    };

    checkDronesMismatch();
  }, [plotList, backendURL]);

  // File upload handler
  const uploadFile = () => {
    if (!selectedFile) {
      toast.warn('No file selected. Please select a file to upload.');
      return;
    }

    // Open confirmation dialog
    setOpenConfirmDialog(true);
  };

  const handleConfirmUpload = () => {
    setOpenConfirmDialog(false);

    const formData = new FormData();
    formData.append('file', selectedFile);
    console.log(`Uploading file to URL: ${backendURL}/import-show`);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${backendURL}/import-show`);

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percentComplete = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percentComplete);
      }
    });

    xhr.addEventListener('readystatechange', () => {
      if (xhr.readyState === XMLHttpRequest.LOADING) {
        setLoading(true);
      } else if (xhr.readyState === XMLHttpRequest.DONE) {
        setLoading(false);
        if (xhr.status === 200) {
          const result = JSON.parse(xhr.responseText);
          if (result.success) {
            toast.success('File uploaded successfully.');
            setUploadCount((prevCount) => prevCount + 1);
            setSelectedFile(null);
            setUploadProgress(0);
          } else {
            toast.error('Error: ' + result.error);
          }
        } else {
          toast.error('Network error. Please try again.');
        }
      }
    });

    xhr.addEventListener('error', () => {
      setLoading(false);
      setUploadProgress(0);
      toast.error('Network error. Please try again.');
    });

    setLoading(true);
    xhr.send(formData);
  };

  const handleCancelUpload = () => {
    setOpenConfirmDialog(false);
    toast.info('Upload cancelled.');
  };

  return (
    <div className="import-show-container">
      <h1>Import Drone Show</h1>
      <div className="intro-section">
        {/* ... existing intro content ... */}
      </div>

      <div className="upload-section">
        <FileUpload onFileSelect={setSelectedFile} selectedFile={selectedFile} />
        <button
          className="upload-button"
          onClick={uploadFile}
          disabled={loading || !selectedFile}
        >
          {loading ? (
            <>
              <CircularProgress size={20} color="inherit" />
              Uploading... {uploadProgress}%
            </>
          ) : (
            'Upload'
          )}
        </button>
      </div>
      <small className="file-requirements">File should be a ZIP containing CSV files.</small>

      {loading && (
        <div className="progress-bar">
          <LinearProgress variant="determinate" value={uploadProgress} />
          <p>{uploadProgress}%</p>
        </div>
      )}

      {dronesMismatchWarning && (
        <p className="warning-message">{dronesMismatchWarning}</p>
      )}
      {coordinateWarnings.map((warning, index) => (
        <p key={index} className="warning-message">
          {warning}
        </p>
      ))}
      {returnWarnings.map((warning, index) => (
        <p key={index} className="soft-warning-message">
          {warning}
        </p>
      ))}

      <div className="upload-info">
        <p>Last upload time: {uploadTime}</p>
      </div>

      <div className="all-drones-plot">
        <img
          src={`${backendURL}/get-show-plots/all_drones.png?key=${uploadCount}`}
          alt="All Drones"
        />
      </div>

      <div className="other-plots">
        {plotList
          .filter((name) => name !== 'all_drones.png')
          .map((filename) => (
            <div key={filename}>
              <img
                src={`${backendURL}/get-show-plots/${encodeURIComponent(filename)}?key=${uploadCount}`}
                alt={filename}
              />
            </div>
          ))}
      </div>

      {/* Confirmation Dialog */}
      <Dialog open={openConfirmDialog} onClose={handleCancelUpload}>
        <DialogTitle>Confirm Upload</DialogTitle>
        <DialogContent>
          Any existing drone show configuration will be overwritten. Are you sure you want to
          proceed?
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelUpload} color="primary">
            Cancel
          </Button>
          <Button onClick={handleConfirmUpload} color="secondary">
            Proceed
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default ImportShow;
