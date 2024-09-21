// app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js

import axios from 'axios';
import { getBackendURL } from './utilities';

/**
 * Handles saving changes to the server, including configData
 * @param {Array} configData - The current configuration data for drones
 */
export const handleSaveChangesToServer = async (configData) => {
    // Validate that there are no missing Drone IDs
    const hwIds = configData.map(drone => parseInt(drone.hw_id));
    const maxId = Math.max(...hwIds);
    for (let i = 1; i <= maxId; i++) {
        if (!hwIds.includes(i)) {
            alert(`Missing Drone ID: ${i}. Please create the missing drone before saving.`);
            return;
        }
    }

    const backendURL = getBackendURL();
    try {
        // Send configData to the backend
        const response = await axios.post(`${backendURL}/save-config-data`, { configData });
        alert(response.data.message);
    } catch (error) {
        console.error("Error saving updated config data:", error);
        if (error.response && error.response.data.message) {
            alert(error.response.data.message);
        } else {
            alert('Error saving data.');
        }
    }
};

/**
 * Handles reverting changes by fetching original data from the server
 * @param {Function} setConfigData - Function to update configData state
 */
export const handleRevertChanges = async (setConfigData) => {
    if (window.confirm("Are you sure you want to reload and lose all current settings?")) {
        const backendURL = getBackendURL();
        try {
            const response = await axios.get(`${backendURL}/get-config-data`);
            setConfigData(response.data);
            alert("Changes reverted successfully.");
        } catch (error) {
            console.error("Error fetching original config data:", error);
            alert("Failed to revert changes.");
        }
    }
};

/**
 * Handles file input changes by parsing CSV and updating configData
 * @param {Object} event - The file input change event
 * @param {Function} setConfigData - Function to update configData state
 */
export const handleFileChange = (event, setConfigData) => {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function (e) {
            const csvData = e.target.result;
            const parsedData = parseCSV(csvData);
            if (parsedData && validateDrones(parsedData)) {
                setConfigData(parsedData);
            } else {
                alert("Invalid CSV structure. Please make sure your CSV matches the required format.");
            }
        };
        reader.readAsText(file);
    }
};

/**
 * Parses CSV data into an array of drone objects
 * @param {string} data - The CSV data as a string
 * @returns {Array|null} - Array of drone objects or null if invalid
 */
export const parseCSV = (data) => {
    const rows = data.trim().split('\n').filter(row => row.trim() !== ''); // Remove empty rows
    const drones = [];
    // Check for correct header
    if (rows[0].trim() !== "hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip") {
        console.log("CSV Header Mismatch!");
        return null; // Invalid CSV structure
    }
    for (let i = 1; i < rows.length; i++) {
        const columns = rows[i].split(',').map(cell => cell.trim()); // Trim each cell value
        if (columns.length === 8) {
            const drone = {
                hw_id: columns[0],
                pos_id: columns[1],
                x: columns[2],
                y: columns[3],
                ip: columns[4],
                mavlink_port: columns[5],
                debug_port: columns[6],
                gcs_ip: columns[7]
            };
            drones.push(drone);
        } else {
            console.log(`Row ${i} has incorrect number of columns.`);
            return null; // Invalid row structure
        }
    }
    return drones;
};

/**
 * Validates the parsed drone data
 * @param {Array} drones - Array of drone objects
 * @returns {boolean} - True if valid, false otherwise
 */
export const validateDrones = (drones) => {
    for (const drone of drones) {
        for (const key in drone) {
            if (!drone[key]) {
                alert(`Empty field detected for Drone ID ${drone.hw_id}, field: ${key}.`);
                console.log(`Empty field detected for Drone ID ${drone.hw_id}, field: ${key}.`);
                return false;
            }
        }
    }
    return true;
};

/**
 * Exports the current configuration data to a CSV file
 * @param {Array} configData - The current configuration data for drones
 */
export const exportConfig = (configData) => {
    const header = ["hw_id", "pos_id", "x", "y", "ip", "mavlink_port", "debug_port", "gcs_ip"];
    const csvRows = configData.map(drone => [
        drone.hw_id,
        drone.pos_id,
        drone.x,
        drone.y,
        drone.ip,
        drone.mavlink_port,
        drone.debug_port,
        drone.gcs_ip
    ].join(","));
    const csvData = [header.join(",")].concat(csvRows).join("\n");

    const blob = new Blob([csvData], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.setAttribute("hidden", "");
    a.setAttribute("href", url);
    a.setAttribute("download", "config_export.csv");
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};
