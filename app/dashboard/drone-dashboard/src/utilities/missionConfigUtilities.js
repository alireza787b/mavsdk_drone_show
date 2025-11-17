//app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js
import axios from 'axios';
import { getBackendURL } from './utilities';
import { convertToLatLon } from './geoutilities'; // Importing the convertToLatLon function
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

/**
 * Validate configuration with backend before saving.
 * Returns validation report for review dialog.
 */
export const validateConfigWithBackend = async (configData, setLoading) => {
    // Define the expected structure
    const expectedFields = ['hw_id', 'pos_id', 'x', 'y', 'ip', 'mavlink_port', 'serial_port', 'baudrate'];

    // Clean and transform the configData
    const cleanedConfigData = configData.map(drone => {
        const cleanedDrone = {};
        expectedFields.forEach(field => {
            cleanedDrone[field] = drone[field] || '';
        });
        return cleanedDrone;
    });

    const backendURL = getBackendURL();

    try {
        setLoading(true);
        toast.info('Validating configuration...', { autoClose: 2000 });

        const response = await axios.post(`${backendURL}/validate-config`, cleanedConfigData);
        return response.data; // Returns validation report

    } catch (error) {
        console.error('Error validating config data:', error);

        if (error.response && error.response.data.message) {
            toast.error(`Validation failed: ${error.response.data.message}`, { autoClose: 10000 });
        } else {
            toast.error(`Error validating configuration: ${error.message || 'Unknown error'}`, { autoClose: 10000 });
        }

        throw error; // Re-throw so caller knows validation failed
    } finally {
        setLoading(false);
    }
};

/**
 * Save configuration to server after validation.
 * This is called AFTER user confirms in review dialog.
 */
export const handleSaveChangesToServer = async(configData, setConfigData, setLoading) => {
    // Define the expected structure (hardware-specific config, gcs_ip/debug_port removed)
    const expectedFields = ['hw_id', 'pos_id', 'x', 'y', 'ip', 'mavlink_port', 'serial_port', 'baudrate'];

    // Clean and transform the configData
    const cleanedConfigData = configData.map(drone => {
        const cleanedDrone = {};
        expectedFields.forEach(field => {
            cleanedDrone[field] = drone[field] || ''; // Default missing fields to an empty string
        });
        return cleanedDrone;
    });

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

        // Show initiating toast
        toast.info('Saving configuration...', { autoClose: 2000 });

        const response = await axios.post(`${backendURL}/save-config-data`, cleanedConfigData);

        // Reload config from server to get trajectory-updated x,y values
        const refreshResponse = await axios.get(`${backendURL}/get-config-data`);
        setConfigData(refreshResponse.data);

        // Success toast with git info
        if (response.data.git_info) {
            if (response.data.git_info.success) {
                toast.success(
                    `Configuration saved and committed to git successfully!`,
                    { autoClose: 5000 }
                );
            } else {
                toast.warning(
                    `Configuration saved, but git commit failed: ${response.data.git_info.message}`,
                    { autoClose: 8000 }
                );
            }
        } else {
            toast.success(
                response.data.message || 'Configuration saved successfully',
                { autoClose: 4000 }
            );
        }

    } catch (error) {
        console.error('Error saving updated config data:', error);

        // Enhanced error toast
        if (error.response && error.response.data.message) {
            toast.error(
                `Save failed: ${error.response.data.message}`,
                { autoClose: 10000 }
            );
        } else {
            toast.error(
                `Error saving configuration: ${error.message || 'Unknown error'}`,
                { autoClose: 10000 }
            );
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
    const rows = data.trim().split('\n').filter(row => row.trim() !== '');
    const drones = [];

    // Expected format: 8 columns (gcs_ip and debug_port removed, now in Params.py)
    const expectedHeader = "hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate";
    const header = rows[0].trim();

    if (header !== expectedHeader) {
        toast.error("Invalid CSV format. Expected 8 columns: hw_id,pos_id,x,y,ip,mavlink_port,serial_port,baudrate");
        return null;
    }

    for (let i = 1; i < rows.length; i++) {
        const columns = rows[i].split(',').map(cell => cell.trim());

        if (columns.length === 8) {
            const drone = {
                hw_id: columns[0],
                pos_id: columns[1],
                x: columns[2],
                y: columns[3],
                ip: columns[4],
                mavlink_port: columns[5],
                serial_port: columns[6],
                baudrate: columns[7]
            };
            drones.push(drone);
        } else {
            toast.error(`Row ${i} has incorrect number of columns (expected 8, got ${columns.length}).`);
            return null;
        }
    }
    return drones;
};

export const validateDrones = (drones) => {
    for (const drone of drones) {
        for (const key in drone) {
            if (!drone[key]) {
                alert(`Empty field detected for Drone ID ${drone.hw_id}, field: ${key}.`);
                return false;
            }
        }
    }
    return true;
};

export const exportConfig = (configData) => {
    const header = ["hw_id", "pos_id", "x", "y", "ip", "mavlink_port", "serial_port", "baudrate"];
    const csvRows = configData.map(drone => [
        drone.hw_id,
        drone.pos_id,
        drone.x,
        drone.y,
        drone.ip,
        drone.mavlink_port,
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