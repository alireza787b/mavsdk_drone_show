import axios from 'axios';
import { getBackendURL } from './utilities';

export const handleSaveChangesToServer = async(configData, setConfigData) => {
    const maxId = Math.max(...configData.map(drone => parseInt(drone.hw_id)));
    for (let i = 1; i <= maxId; i++) {
        if (!configData.some(drone => parseInt(drone.hw_id) === i)) {
            alert(`Missing Drone ID: ${i}. Please create the missing drone before saving.`);
            return;
        }
    }

    const backendURL = getBackendURL();
    try {
        const response = await axios.post(`${backendURL}/save-config-data`, configData);
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
    const header = ["hw_id", "pos_id", "x", "y", "ip", "mavlink_port,debug_port,gcs_ip"];
    const csvRows = configData.map(drone => [drone.hw_id, drone.pos_id, drone.x, drone.y, drone.ip, drone.mavlink_port, drone.debug_port, drone.gcs_ip].join(","));
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