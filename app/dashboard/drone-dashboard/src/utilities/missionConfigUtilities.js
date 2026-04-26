//app/dashboard/drone-dashboard/src/utilities/missionConfigUtilities.js
import { convertToLatLon } from './geoutilities'; // Importing the convertToLatLon function
import { normalizeDroneConfigData, toBackendConfigDrone } from './missionIdentityUtils';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import {
    getFleetConfigResponse,
    saveFleetConfigResponse,
    validateFleetConfigResponse,
} from '../services/gcsApiService';

// Core required fields — must always be present on every drone
const CORE_FIELDS = ['hw_id', 'pos_id', 'ip', 'mavlink_port', 'serial_port', 'baudrate'];

/**
 * Clean a drone object for sending to the backend.
 * Preserves ALL fields (including custom ones added via JSON),
 * ensures core fields have values, and removes transient UI-only fields.
 */
const cleanDroneForBackend = (drone) => {
    const cleanedDrone = { ...drone }; // Preserve ALL fields (including custom ones)
    // Ensure core fields have values
    CORE_FIELDS.forEach(field => {
        if (cleanedDrone[field] === undefined || cleanedDrone[field] === null) {
            cleanedDrone[field] = '';
        }
    });
    // Remove transient UI-only fields
    delete cleanedDrone.x;
    delete cleanedDrone.y;
    delete cleanedDrone.isNew;
    delete cleanedDrone.custom_fields;

    return toBackendConfigDrone(cleanedDrone) || cleanedDrone;
};

/**
 * Validate configuration with backend before saving.
 * Returns validation report for review dialog.
 *
 * NOTE: x,y positions are NOT sent — they come from trajectory files only.
 */
export const validateConfigWithBackend = async (configData, setLoading) => {
    // Clean and transform the configData (preserves all fields, ensures core fields exist)
    const cleanedConfigData = configData.map(cleanDroneForBackend);

    try {
        setLoading(true);
        toast.info('Validating configuration...', { autoClose: 2000 });

        const response = await validateFleetConfigResponse(cleanedConfigData);
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
 *
 * NOTE: x,y positions are NOT saved — they come from trajectory files only.
 */
export const handleSaveChangesToServer = async(configData, setConfigData, setLoading) => {
    // Clean and transform the configData (preserves all fields, ensures core fields exist)
    const cleanedConfigData = configData.map(cleanDroneForBackend);

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

    try {
        setLoading(true); // Set loading state to true

        // Show initiating toast
        toast.info('Saving configuration...', { autoClose: 2000 });

        const response = await saveFleetConfigResponse(cleanedConfigData);

        // Reload config from server to get latest saved state
        const refreshResponse = await getFleetConfigResponse();
        setConfigData(refreshResponse.data);

        // Success toast with git info
        const gitInfo = response.data.git_result || response.data.git_info;
        if (gitInfo) {
            if (gitInfo.success) {
                toast.success(
                    `Configuration saved and committed to git successfully.

Reboot all drones from the Actions tab to apply changes.`,
                    { autoClose: 8000 }
                );
            } else {
                toast.warning(
                    `Configuration saved, but git commit failed: ${gitInfo.message}`,
                    { autoClose: 8000 }
                );
            }
        } else {
            toast.success(
                `${response.data.message || 'Configuration saved successfully'}

Reboot all drones from the Actions tab to apply changes.`,
                { autoClose: 8000 }
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
        try {
            const response = await getFleetConfigResponse();
            setConfigData(response.data);
        } catch (error) {
            console.error("Error fetching original config data:", error);
        }
    }
};

export const handleFileChange = (event, setConfigData) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        try {
            // Try JSON first
            const data = JSON.parse(text);
            const drones = data.drones || (Array.isArray(data) ? data : []);
            if (drones.length > 0) {
                setConfigData(normalizeDroneConfigData(drones));
                toast.success(`Imported ${drones.length} drones from JSON`);
            } else {
                toast.error('No drones found in JSON file');
            }
        } catch {
            // Fall back to CSV parsing
            const drones = parseCSV(text);
            if (drones && validateDrones(drones)) {
                setConfigData(normalizeDroneConfigData(drones));
                toast.success(`Imported ${drones.length} drones from CSV`);
            } else {
                toast.error('Invalid file format. Please use JSON or CSV format.');
            }
        }
    };
    reader.readAsText(file);
};

export const parseCSV = (data) => {
    const rows = data.trim().split('\n').filter(row => row.trim() !== '');
    const drones = [];

    const headerColumns = rows[0].trim().split(',').map(h => h.trim());

    // Core fields must be present; extra columns are allowed (custom fields)
    const coreHeaders = ['hw_id', 'pos_id', 'ip', 'mavlink_port', 'serial_port', 'baudrate'];
    const missingHeaders = coreHeaders.filter(h => !headerColumns.includes(h));
    if (missingHeaders.length > 0) {
        toast.error(`Invalid CSV format. Missing required columns: ${missingHeaders.join(', ')}`);
        return null;
    }

    for (let i = 1; i < rows.length; i++) {
        const columns = rows[i].split(',').map(cell => cell.trim());

        if (columns.length >= coreHeaders.length) {
            const drone = {};
            headerColumns.forEach((header, idx) => {
                drone[header] = columns[idx] || '';
            });
            drones.push(drone);
        } else {
            toast.error(`Row ${i} has incorrect number of columns (expected at least ${coreHeaders.length}, got ${columns.length}).`);
            return null;
        }
    }
    return drones;
};

export const validateDrones = (drones) => {
    for (const drone of drones) {
        for (const field of ['hw_id', 'pos_id', 'ip', 'mavlink_port']) {
            if (drone[field] === undefined || drone[field] === null || drone[field] === '') {
                alert(`Empty field detected for Drone ID ${drone.hw_id}, field: ${field}.`);
                return false;
            }
        }
    }
    return true;
};

/**
 * Export config as JSON (primary format).
 */
export const exportConfigJSON = (configData) => {
    const data = { version: 1, drones: configData.map(cleanDroneForBackend) };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.setAttribute('hidden', '');
    a.setAttribute('href', url);
    a.setAttribute('download', 'config.json');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};

/**
 * Export config as CSV (backward-compatible, core fields only).
 */
export const exportConfigCSV = (configData) => {
    const header = ["hw_id", "pos_id", "ip", "mavlink_port", "serial_port", "baudrate"];
    const csvRows = configData.map(drone => {
        const cleanedDrone = cleanDroneForBackend(drone);
        return [
            cleanedDrone.hw_id,
            cleanedDrone.pos_id,
            cleanedDrone.ip,
            cleanedDrone.mavlink_port,
            cleanedDrone.serial_port ?? '',
            cleanedDrone.baudrate ?? 0
        ].join(",");
    });
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

// Backward-compatible alias
export const exportConfig = exportConfigJSON;

/**
 * Generate KML from drone positions.
 * NOTE: drones array should include x,y from trajectory CSV (fetched via API)
 * For example: drones = [{hw_id, pos_id, x, y, ...}, ...]
 */
export const generateKML = (drones, originLat, originLon) => {
    let kml = `<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
    <Document>`;

    drones.forEach((drone) => {
        // x,y should be provided from trajectory files (not config.json)
        if (drone.x !== undefined && drone.y !== undefined) {
            const { latitude, longitude } = convertToLatLon(
                originLat,
                originLon,
                parseFloat(drone.x),
                parseFloat(drone.y)
            );

            kml += `
        <Placemark>
          <name>Position ${drone.pos_id} (HW ${drone.hw_id})</name>
          <description>Position: ${drone.pos_id}, Hardware ID: ${drone.hw_id}</description>
          <Point>
            <coordinates>${longitude},${latitude},0</coordinates>
          </Point>
        </Placemark>`;
        }
    });

    kml += `
    </Document>
    </kml>`;

    return kml;
};
