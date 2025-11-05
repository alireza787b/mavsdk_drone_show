//app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js
import axios from 'axios';
import { getBackendURL } from './utilities';
import { convertToLatLon } from './geoutilities'; // Importing the convertToLatLon function
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

export const handleSaveChangesToServer = async(configData, setConfigData, setLoading) => {
    // Define the expected structure (updated to include hardware-specific config)
    const expectedFields = ['hw_id', 'pos_id', 'x', 'y', 'ip', 'mavlink_port', 'debug_port', 'gcs_ip', 'serial_port', 'baudrate'];

    // Clean and transform the configData
    const cleanedConfigData = configData.map(drone => {
        const cleanedDrone = {};
        expectedFields.forEach(field => {
            cleanedDrone[field] = drone[field] || ''; // Default missing fields to an empty string
        });
        return cleanedDrone;
    });

    console.log('Cleaned ConfigData being sent to server:', JSON.stringify(cleanedConfigData, null, 2)); // Log cleaned data

    const hwIds = cleanedConfigData.map(drone => parseInt(drone.hw_id));
    const missingIds = [];
    const maxId = Math.max(...hwIds);

    for (let i = 1; i <= maxId; i++) {
        if (!hwIds.includes(i)) {
            missingIds.push(i);
        }
    }

    if (missingIds.length > 0) {
        toast.warn(`Missing Drone IDs: ${missingIds.join(', ')}. Please check before saving.`);
    }

    const backendURL = getBackendURL();

    try {
        setLoading(true); // Set loading state to true
        const response = await axios.post(`${backendURL}/save-config-data`, cleanedConfigData);
        toast.success(response.data.message);
    } catch (error) {
        console.error('Error saving updated config data:', error);
        if (error.response && error.response.data.message) {
            toast.error(error.response.data.message);
        } else {
            toast.error('Error saving data.');
        }
    } finally {
        setLoading(false); // Set loading state to false
    }
};



export const handleRevertChanges = async(setConfigData) => {
    if (window.confirm("Are you sure you want to reload and lose all current settings?")) {
        const backendURL = getBackendURL();
        try {
            const response = await axios.get(`${backendURL}/get-config-data`);
            setConfigData(response.data);
        } catch (error) {
            console.error("Error fetching original config data:", error);
        }
    }
};

export const handleFileChange = (event, setConfigData) => {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const csvData = e.target.result;
            const drones = parseCSV(csvData);
            if (drones && validateDrones(drones)) {
                setConfigData(drones);
            } else {
                alert("Invalid CSV structure. Please make sure your CSV matches the required format.");
            }
        };
        reader.readAsText(file);
    }
};

export const parseCSV = (data) => {
    const rows = data.trim().split('\n').filter(row => row.trim() !== ''); // Trim to remove possible whitespace and filter out empty rows
    const drones = [];

    // Support both old (8 columns) and new (10 columns) formats for backward compatibility
    const header = rows[0].trim();
    const isOldFormat = header === "hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip";
    const isNewFormat = header === "hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate";

    if (!isOldFormat && !isNewFormat) {
        console.log("CSV Header Mismatch! Expected either 8-column (legacy) or 10-column (new with serial_port, baudrate) format.");
        toast.error("Invalid CSV format. Please check the header row.");
        return null; // Invalid CSV structure
    }

    // Notify user if old format detected
    if (isOldFormat) {
        toast.info("Legacy CSV format detected. Serial port and baudrate will be set to defaults (/dev/ttyS0, 57600).", {
            autoClose: 5000
        });
    }

    for (let i = 1; i < rows.length; i++) {
        const columns = rows[i].split(',').map(cell => cell.trim()); // Trim each cell value

        if (isOldFormat && columns.length === 8) {
            // Auto-upgrade old format with default values
            const drone = {
                hw_id: columns[0],
                pos_id: columns[1],
                x: columns[2],
                y: columns[3],
                ip: columns[4],
                mavlink_port: columns[5],
                debug_port: columns[6],
                gcs_ip: columns[7],
                serial_port: '/dev/ttyS0',  // Default for Raspberry Pi 4
                baudrate: '57600'            // Standard baudrate
            };
            drones.push(drone);
        } else if (isNewFormat && columns.length === 10) {
            // New format with all columns
            const drone = {
                hw_id: columns[0],
                pos_id: columns[1],
                x: columns[2],
                y: columns[3],
                ip: columns[4],
                mavlink_port: columns[5],
                debug_port: columns[6],
                gcs_ip: columns[7],
                serial_port: columns[8],
                baudrate: columns[9]
            };
            drones.push(drone);
        } else {
            console.log(`Row ${i} has incorrect number of columns (expected ${isOldFormat ? 8 : 10}, got ${columns.length}).`);
            toast.error(`Row ${i} has incorrect number of columns.`);
            return null; // Invalid row structure
        }
    }
    return drones;
};

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

export const exportConfig = (configData) => {
    const header = ["hw_id", "pos_id", "x", "y", "ip", "mavlink_port", "debug_port", "gcs_ip", "serial_port", "baudrate"];
    const csvRows = configData.map(drone => [
        drone.hw_id,
        drone.pos_id,
        drone.x,
        drone.y,
        drone.ip,
        drone.mavlink_port,
        drone.debug_port,
        drone.gcs_ip,
        drone.serial_port || '/dev/ttyS0',  // Default if missing
        drone.baudrate || '57600'            // Default if missing
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

export const generateKML = (drones, originLat, originLon) => {
    let kml = `<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
    <Document>`;

    drones.forEach((drone) => {
        const { latitude, longitude } = convertToLatLon(
            originLat,
            originLon,
            parseFloat(drone.x),
            parseFloat(drone.y)
        );

        kml += `
        <Placemark>
          <name>Drone ${drone.hw_id}</name>
          <description>HW ID: ${drone.hw_id}, POS ID: ${drone.pos_id}</description>
          <Point>
            <coordinates>${longitude},${latitude},0</coordinates>
          </Point>
        </Placemark>`;
    });

    kml += `
    </Document>
    </kml>`;

    return kml;
};