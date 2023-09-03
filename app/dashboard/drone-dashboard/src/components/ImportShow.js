// ImportShow.js
import React, { useState, useEffect } from 'react';

import '../styles/ImportShow.css';
import { getBackendURL } from '../utilities';  // Adjust the path according to the location of utilities.js


const ImportShow = () => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [responseMessage, setResponseMessage] = useState('');
    const [plotList, setPlotList] = useState([]);
    const [uploadTime, setUploadTime] = useState(null);
    const [uploadCount, setUploadCount] = useState(0);
    const [dronesMismatchWarning, setDronesMismatchWarning] = useState(null);
    const [coordinateWarnings, setCoordinateWarnings] = useState([]);
    const [returnWarnings, setReturnWarnings] = useState([]);
    
    useEffect(() => {
        async function fetchPlots() {
          const backendURL = getBackendURL();
          const response = await fetch(`${backendURL}/get-show-plots`);
          const data = await response.json();
      
          console.log("Fetched plot list:", data.filenames);  // Debug output
      
          setPlotList(data.filenames || []);
          setUploadTime(data.uploadTime || "N/A");
        }
      
        fetchPlots();
      }, [responseMessage, uploadCount]);
      
      useEffect(() => {
        async function checkDronesMismatch() {
          const backendURL = getBackendURL();
          const configResponse = await fetch(`${backendURL}/get-config-data`);
          const configData = await configResponse.json();
      
          const configMap = configData.reduce((acc, drone) => {
            acc[drone.hw_id] = { x: parseFloat(drone.x), y: parseFloat(drone.y) };
            return acc;
          }, {});
      
          const coordinateWarnings = [];
          const returnWarnings = [];
          let droneCountWarning = null;
      
          // 1. Check for drone number mismatch
          if (configData.length !== (plotList.length - 1)) {
            droneCountWarning = `The number of drones in the uploaded show (${plotList.length - 1}) does not match the number in the config file (${configData.length}).`;
          }
      
          // 2. and 3. Check for coordinate mismatches
          for (const [hw_id, { x: configX, y: configY }] of Object.entries(configMap)) {
            try {
              const rowResponse = await fetch(`${backendURL}/get-first-last-row/${hw_id}`);
              const rowData = await rowResponse.json();
      
              const firstRowX = parseFloat(rowData.firstRow.x);
              const firstRowY = parseFloat(rowData.firstRow.y);
              const lastRowX = parseFloat(rowData.lastRow.x);
              const lastRowY = parseFloat(rowData.lastRow.y);
      
              if (configX !== firstRowX || configY !== firstRowY) {
                coordinateWarnings.push(`Drone ${hw_id} has mismatch in initial launch point. Config: (${configX}, ${configY}), CSV: (${firstRowX}, ${firstRowY})`);
              }
      
              if (firstRowX !== lastRowX || firstRowY !== lastRowY) {
                returnWarnings.push(`Drone ${hw_id} has different return point. Start: (${firstRowX}, ${firstRowY}), End: (${lastRowX}, ${lastRowY})`);
              }
      
            } catch (error) {
              console.warn(`Could not fetch data for drone ${hw_id}. Skipping...`);
            }
          }
      
          setCoordinateWarnings(coordinateWarnings);
          setReturnWarnings(returnWarnings);
          setDronesMismatchWarning(droneCountWarning);
        }
      
        checkDronesMismatch();
      }, [plotList]);
      
      
      
    
      

    const uploadFile = async () => {
        const userConfirmed = window.confirm("Any existing drone show configuration will be overwritten. Are you sure you want to proceed?");
        if (userConfirmed) {

        const formData = new FormData();
        formData.append('file', selectedFile);
        
        const backendURL = getBackendURL();  // Get the backend URL using your utility function
      
        try {
          const response = await fetch(`${backendURL}/import-show`, {
            method: 'POST',
            body: formData
          });
          
          const result = await response.json();
          
          if (result.success) {
            setResponseMessage('File uploaded successfully.');
            setUploadCount(uploadCount + 1); // Increment the upload count
        } else {
            setResponseMessage('Error: ' + result.error);
          }
        } catch (error) {
          setResponseMessage('Network error. Please try again.');
        }
    }else {
        setResponseMessage('Upload cancelled by user.');
      }

      };
      
      
  
    const handleFileChange = (e) => {
      const file = e.target.files[0];
      if (file) {
        setSelectedFile(file);
      }
    };
  

    const [dragging, setDragging] = useState(false);

    const handleDragEnter = (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(true);
    };
    
    const handleDragLeave = (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
    };
    
    const handleDragOver = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    
    const handleDrop = (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
    
      let files = [...e.dataTransfer.files];
      // handle the files just like handleFileChange
    };

  return (
    <div className="import-show-container">
      <h1>Import Drone Show</h1>
<div className="intro-section">
  <p>Welcome to the advanced Drone Show Import utility of our Swarm Dashboard. This powerful tool automates and streamlines the entire workflow for your drone shows. Here's what you can accomplish:</p>
  <ul>
    <li><strong>Upload</strong>: Seamlessly upload ZIP files that you've exported from SkyBrush.</li>
    <li><strong>Process</strong>: Our algorithm will automatically process and adapt these files to be compatible with our system.</li>
    <li><strong>Visualize</strong>: Automatically generate insightful plots for your drone paths.</li>
    <li><strong>Update</strong>: Your mission configuration file will be auto-updated based on the processed data.</li>
    <li><strong>Access</strong>: Retrieve the processed plot images and CSV files from the <code>shapes/swarm</code> directory.</li>
  </ul>
  <p>
    SkyBrush is a plugin compatible with Blender and 3D Max, designed for creating drone show animations. Learn how to create stunning animations for your drones in our <a href="https://youtu.be/wctmCIzpMpY" target="_blank" rel="noreferrer" className="tutorial-link">YouTube tutorial</a>.
  </p>
  <p>
    For advanced users who require more control over the processing parameters, you can directly execute our <code>process_formation.py</code> Python script. The files will be exported to the <code>shapes/swarm</code> directory.
  </p>
</div>

      <div className="upload-section">
      <div
  className={`drop-zone ${dragging ? 'dragging' : ''}`}
  onDrop={handleDrop}
  onDragOver={handleDragOver}
  onDragEnter={handleDragEnter}
  onDragLeave={handleDragLeave}
>
  <input type="file" accept=".zip" onChange={handleFileChange} />
  {dragging && <div>Drop here ...</div>}
</div>      <button className="upload-button" onClick={uploadFile}>Upload</button>
              </div>
              <small className="file-requirements">File should be a ZIP containing CSV files.</small>

              <p className={`response-message ${responseMessage.includes('successfully') ? 'success' : 'failure'}`}>{responseMessage}</p>
          

{dronesMismatchWarning && (
  <p className="warning-message">
    {dronesMismatchWarning}
  </p>
)}
{coordinateWarnings.map((warning, index) => (
  <p key={index} className="warning-message">{warning}</p>
))}
{returnWarnings.map((warning, index) => (
  <p key={index} className="soft-warning-message">{warning}</p>
))}





              <div className="upload-info">
        <p>Last upload time: {uploadTime}</p>
    </div>

    <div className="all-drones-plot">
    <img src={`${getBackendURL()}/get-show-plots/all_drones.png?key=${uploadCount}`} alt="All Drones" />
</div>

<div className="other-plots">
    {plotList.filter(name => name !== "all_drones.png").map(filename => (
        <div key={filename}>
            <img src={`${getBackendURL()}/get-show-plots/${encodeURIComponent(filename)}?key=${uploadCount}`} alt={filename} />
        </div>
    ))}
</div>



    </div>
    
    
  );
};

export default ImportShow;
