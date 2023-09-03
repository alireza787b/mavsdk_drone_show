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
      
          console.log("Number of drones in config:", configData.length);  // Debug output
          console.log("Number of plots:", plotList.length);  // Debug output
      
          if (configData.length !== (plotList.length -1)) {
            console.log("Mismatch detected!");  // Debug output
            setDronesMismatchWarning('The number of drones in the uploaded show does not match the number in config.csv.');
          } else {
            console.log("No mismatch detected.");  // Debug output
            setDronesMismatchWarning(null);
          }
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
    Please check and update your 
    <a href="http://localhost:3000/mission-config" target="_blank" rel="noreferrer">Mission Configuration</a>.
  </p>
)}


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
