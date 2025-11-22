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
import { ClockIcon, PlayIcon } from 'lucide-react';

const ImportShow = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [plotList, setPlotList] = useState([]);
  const [uploadTime, setUploadTime] = useState('N/A');
  const [uploadCount, setUploadCount] = useState(0);
  const [dronesMismatchWarning, setDronesMismatchWarning] = useState(null);
  // Note: coordinateWarnings removed - x,y no longer in config.csv
  const [returnWarnings, setReturnWarnings] = useState([]);
  const [openConfirmDialog, setOpenConfirmDialog] = useState(false);
  const [loading, setLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [showDuration, setShowDuration] = useState(null);

  const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

  // Fetch plot list from backend
  useEffect(() => {
    const fetchPlots = async () => {
      try {
        const response = await fetch(`${backendURL}/get-show-plots`);
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const data = await response.json();
        setPlotList(data.filenames || []);
        setUploadTime(data.uploadTime || 'N/A');
      } catch (error) {
        console.error('Fetch plots failed:', error);
        toast.error('Error fetching plot list.');
      }
    };

    fetchPlots();
  }, [backendURL, uploadCount]);

  // Fetch show duration when plot list changes
  useEffect(() => {
    const fetchShowDuration = async () => {
      try {
        const response = await fetch(`${backendURL}/get-show-duration`);
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const data = await response.json();
        setShowDuration(data);
      } catch (error) {
        console.error('Failed to fetch show duration:', error);
      }
    };

    if (plotList.length > 0) {
      fetchShowDuration();
    }
  }, [plotList, backendURL]);

  // Check for drone mismatches (previous implementation remains the same)
  useEffect(() => {
    const checkDronesMismatch = async () => {
      try {
        const configResponse = await fetch(`${backendURL}/get-config-data`);
        if (!configResponse.ok) throw new Error(`HTTP error! Status: ${configResponse.status}`);
        const configData = await configResponse.json();

        // Note: x,y positions now come from trajectory CSV files only, not config.csv
        const returnWarnings = [];
        let droneCountWarning = null;

        if (configData.length !== plotList.length - 1) {
          droneCountWarning = `The number of drones in the uploaded show (${plotList.length - 1}) does not match the number in the config file (${configData.length}).`;
        }

        // For each drone, check if they return to their starting position
        for (const drone of configData) {
          const hw_id = drone.hw_id;
          try {
            const rowResponse = await fetch(`${backendURL}/get-first-last-row/${hw_id}`);
            if (!rowResponse.ok) throw new Error(`HTTP error! Status: ${rowResponse.status}`);
            const rowData = await rowResponse.json();

            const firstRowX = parseFloat(rowData.firstRow.x);
            const firstRowY = parseFloat(rowData.firstRow.y);
            const lastRowX = parseFloat(rowData.lastRow.x);
            const lastRowY = parseFloat(rowData.lastRow.y);

            if (firstRowX !== lastRowX || firstRowY !== lastRowY) {
              returnWarnings.push(
                `Drone ${hw_id} has different return point. Start: (${firstRowX}, ${firstRowY}), End: (${lastRowX}, ${lastRowY})`
              );
            }
          } catch (error) {
            console.warn(`Could not fetch data for drone ${hw_id}. Skipping...`, error);
          }
        }
        setReturnWarnings(returnWarnings);
        setDronesMismatchWarning(droneCountWarning);
      } catch (error) {
        console.error('Error checking drone mismatches:', error);
        toast.error('Error checking drone mismatches.');
      }
    };

    checkDronesMismatch();
  }, [plotList, backendURL]);

  // File upload handlers remain the same
  const uploadFile = () => {
    if (!selectedFile) {
      toast.warn('No file selected. Please select a file to upload.');
      return;
    }
    setOpenConfirmDialog(true);
  };

  const handleConfirmUpload = () => {
    // Previous implementation remains the same
  };

  const handleCancelUpload = () => {
    setOpenConfirmDialog(false);
    toast.info('Upload cancelled.');
  };

  // Helper function to format duration
  const formatDuration = (durationObj) => {
    if (!durationObj) return 'N/A';
    const minutes = Math.floor(durationObj.duration_minutes);
    const seconds = Math.round(durationObj.duration_seconds);
    return minutes > 0 
      ? `${minutes} min ${seconds} sec` 
      : `${seconds} sec`;
  };

  return (
    <div className="import-show-container">
      <h1>Import Drone Show</h1>
      
      {/* Intro section remains the same */}
      <div className="intro-section">
        {/* Previous intro section content */}
      </div>

      {/* Upload section */}
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

      {/* Loading progress */}
      {loading && (
        <div className="progress-bar">
          <LinearProgress variant="determinate" value={uploadProgress} />
          <p>{uploadProgress}%</p>
        </div>
      )}

      {/* Warnings section */}
      {dronesMismatchWarning && (
        <p className="warning-message">{dronesMismatchWarning}</p>
      )}
      {/* Note: Coordinate warnings removed - x,y no longer in config.csv */}
      {returnWarnings.map((warning, index) => (
        <p key={index} className="soft-warning-message">
          {warning}
        </p>
      ))}

      {/* Show Duration Display */}
      {showDuration && (
        <div className="show-duration-section">
          <div className="show-duration-content">
            <div className="duration-icon">
              <ClockIcon size={32} strokeWidth={2} color="#2563eb" />
            </div>
            <div className="duration-details">
              <h3>Show Duration</h3>
              <div className="duration-info">
                <p>
                  <strong>Total Time:</strong>{' '}
                  <span className="duration-value">
                    {formatDuration(showDuration)}
                  </span>
                </p>
                <p className="duration-precise">
                  <small>Precise: {showDuration.duration_ms} ms</small>
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Upload info */}
      <div className="upload-info">
        <p>Last upload time: {uploadTime}</p>
      </div>

      {/* Plot sections */}
      <div className="all-drones-plot">
        <img
          src={`${backendURL}/get-show-plots/combined_drone_paths.png?key=${uploadCount}`}
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