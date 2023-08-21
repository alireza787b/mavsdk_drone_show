import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from './DroneGraph';
import SwarmPlots from './SwarmPlots';
import DroneCard from './DroneCard';
import { getBackendURL } from '../utilities';  // Adjust the path according to the location of utilities.js



const transformToGraphData = (swarmData) => {
    const nodes = swarmData.map(drone => ({
        data: { id: drone.hw_id, label: drone.hw_id, ...drone } // Set label to hw_id
    }));

    const edges = swarmData
        .filter(drone => drone.follow !== '0')
        .map(drone => ({
            data: { source: drone.hw_id, target: drone.follow }
        }));

    return [...nodes, ...edges];
};

function categorizeDrones(swarmData) {
    const topLeaders = swarmData.filter(drone => drone.follow === '0');
    const topLeaderIdsSet = new Set(topLeaders.map(leader => leader.hw_id));

    // Count followers for each drone
    const followerCounts = {};
    swarmData.forEach(drone => {
        if (!followerCounts[drone.follow]) {
            followerCounts[drone.follow] = 0;
        }
        followerCounts[drone.follow]++;
    });

    // Identify intermediate leaders
    const intermediateLeaders = swarmData.filter(drone => 
        !topLeaderIdsSet.has(drone.hw_id) && followerCounts[drone.hw_id]
    );
    const intermediateLeaderIdsSet = new Set(intermediateLeaders.map(drone => drone.hw_id));
    
    return {
        topLeaders,
        intermediateLeaders,
        topLeaderIdsSet,
        intermediateLeaderIdsSet
    };
}

function isEqual(arr1, arr2) {
    return JSON.stringify(arr1) === JSON.stringify(arr2);
}



function SwarmDesign() {
    console.log("SwarmDesign rendered");

    const [swarmData, setSwarmData] = useState([]);
    const [configData, setConfigData] = useState([]);
    const { topLeaders, intermediateLeaders } = categorizeDrones(swarmData);
    const [selectedDroneId, setSelectedDroneId] = useState(null); // 1. Added state for selected drone ID
    const [changes, setChanges] = useState({ added: [], removed: [] });

    const handleSaveChanges = (hw_id, updatedDroneData) => {
        setSwarmData(prevDrones => prevDrones.map(drone => drone.hw_id === hw_id ? updatedDroneData : drone));
    };

    
    const handleDroneCardClick = (droneId) => {
        setSelectedDroneId(droneId);
    };

// useEffect for fetching data
useEffect(() => {
    const backendURL = getBackendURL();

    const fetchSwarmData = axios.get(`${backendURL}/get-swarm-data`);
    const fetchConfigData = axios.get(`${backendURL}/get-config-data`);

    Promise.all([fetchSwarmData, fetchConfigData])
        .then(([swarmResponse, configResponse]) => {
            setSwarmData(swarmResponse.data);
            setConfigData(configResponse.data);
        })
        .catch(error => {
            console.error("Error fetching data:", error);
        });

}, []);  // Run only once on component mount

// useEffect for synchronizing swarmData based on configData
useEffect(() => {
    if (swarmData.length === 0 || configData.length === 0) return; // Ensure we have data

    let updatedSwarmData = [...swarmData];
// Update changes
const addedDrones = configData.filter(configDrone => !swarmData.some(drone => drone.hw_id === configDrone.hw_id)).map(drone => drone.hw_id);
const removedDrones = swarmData.filter(swarmDrone => !configData.some(configDrone => configDrone.hw_id === swarmDrone.hw_id)).map(drone => drone.hw_id);
setChanges({ added: addedDrones, removed: removedDrones });
    // Add missing drones to swarmData
    configData.forEach(configDrone => {
        if (!swarmData.some(drone => drone.hw_id === configDrone.hw_id)) {
            updatedSwarmData.push({
                hw_id: configDrone.hw_id,
                follow: '0',
                offset_n: '0',
                offset_e: '0',
                offset_alt: '0'
            });
        }
    });

    // Remove extra drones from swarmData
    updatedSwarmData = updatedSwarmData.filter(swarmDrone =>
        configData.some(configDrone => configDrone.hw_id === swarmDrone.hw_id)
    );

    if (!isEqual(swarmData, updatedSwarmData)) {
        setSwarmData(updatedSwarmData);
    }

}, [configData]);  // Run whenever configData changes

    

    const dronesFollowing = (leaderId) => {
        return swarmData.filter(drone => drone.follow === leaderId).map(drone => drone.hw_id);
    };

    const handleSaveChangesToServer = () => {
        const changesSummary = swarmData.map(drone => {
            const role = drone.follow === '0' ? 'Top Leader' : 
                        (dronesFollowing(drone.hw_id).length ? 'Intermediate Leader' : 'Follower');
            return `Drone ${drone.hw_id}: ${role} ${role !== 'Top Leader' ? `(Follows Drone ${drone.follow})` : ''} with Offsets (m) North:${drone.offset_n} East:${drone.offset_e} Altitude:${drone.offset_alt}`;
        }).join('\n');
    
        const isConfirmed = window.confirm(`Are you sure you want to save the following changes?\n\n${changesSummary}`);
        if (isConfirmed) {
            saveUpdatedSwarmData();
        }
    };
    
    
    const handleRevertChanges = () => {
        if (window.confirm("Are you sure you want to reload and lose all current settings?")) {
            fetchOriginalSwarmData();
        }
    };
    

    const fetchOriginalSwarmData = () => {
        const backendURL = getBackendURL();

        const fetchSwarmData = axios.get(`${backendURL}/get-swarm-data`);
        const fetchConfigData = axios.get(`${backendURL}/get-config-data`);
    
        Promise.all([fetchSwarmData, fetchConfigData])
            .then(([swarmResponse, configResponse]) => {
                setSwarmData(swarmResponse.data);
                setConfigData(configResponse.data);
            })
            .catch(error => {
                console.error("Error fetching data:", error);
            });
    };
    

    const saveUpdatedSwarmData = () => {
        const backendURL = getBackendURL();

        axios.post(`${backendURL}/save-swarm-data`, swarmData)
            .then(response => {
                if (response.status === 200) {
                    alert(response.data.message);
                    // Refetch the data after a successful save:
                    fetchOriginalSwarmData();
                } else {
                    alert('Error saving data.');
                }
            })
            .catch(error => {
                console.error("Error saving updated swarm data:", error);
                alert('Error saving data.');
            });
    };
    

    const handleCSVImport = (event) => {
        const file = event.target.files[0];
        if (file) {
            let parsedData = Papa.parse(file, {
                complete: (result) => {
                    const header = result.data[0].map(column => column.trim());
                    if (header.toString() !== ["hw_id", "follow", "offset_n", "offset_e", "offset_alt"].toString()) {
                        alert("CSV structure is incorrect. Please check the column headers and order.");
                        return;
                    }
    
                    parsedData = result.data.slice(1).map(row => ({
                        hw_id: row[0],
                        follow: row[1],
                        offset_n: row[2],
                        offset_e: row[3],
                        offset_alt: row[4]
                    }));
                    parsedData = parsedData.filter(drone => drone.hw_id && drone.hw_id.trim() !== "");
    
                    // console.log("Parsed CSV data:", parsedData);
    
                    setSwarmData(parsedData);
                },
                header: false
            });
        }
    };
    
    
const handleCSVExport = () => {
    const orderedSwarmData = swarmData.map(drone => ({
        hw_id: drone.hw_id,
        follow: drone.follow,
        offset_n: drone.offset_n,
        offset_e: drone.offset_e,
        offset_alt: drone.offset_alt
    }));
    const csvContent = Papa.unparse(orderedSwarmData);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", "swarm_export.csv");
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
};



    return (
        <div className="swarm-design-container">
    
    <div className={`control-buttons ${changes.added.length > 0 || changes.removed.length > 0 ? 'show-notification' : ''}`}>
    {changes.added.length > 0 && 
        <div className="notification-container">
            <span className="notification-icon">⚠️</span>
            <p className="notification-text">
                Drone(s) {changes.added.join(', ')} do not exist in swarm data and have been added.
            </p>
        </div>
    }

    {changes.removed.length > 0 && 
        <div className="notification-container">
            <span className="notification-icon">⚠️</span>
            <p className="notification-text">
                Drone(s) {changes.removed.join(', ')} exist in swarm data but not in config and have been removed.
            </p>
        </div>
    }

    <div className="primary-actions">
        <button 
            className={`save ${changes.added.length > 0 || changes.removed.length > 0 ? 'pending-changes' : ''}`} 
            onClick={handleSaveChangesToServer}
        >
            Save Changes
        </button>
    </div>
    
    <div className="secondary-actions">
        <button className="revert" onClick={handleRevertChanges}>Revert</button>
        <label className="file-upload-btn">
            Import CSV
            <input type="file" id="csvInput" accept=".csv" onChange={handleCSVImport} />
        </label>
        <button className="export-config" onClick={handleCSVExport}>Export CSV</button>
    </div>
</div>



            

            <div className="swarm-container">
                {swarmData.length ? swarmData.map(drone => (
                   <DroneCard 
                   key={drone.hw_id}
                   drone={drone}
                   allDrones={swarmData}
                   onSaveChanges={handleSaveChanges}
                   isSelected={selectedDroneId === drone.hw_id}  // Add this line
               />
               
                
                )) : <p>No data available for swarm configuration.</p>}
            </div>
            
            <div className="swarm-graph-container">
            <DroneGraph swarmData={swarmData} onSelectDrone={setSelectedDroneId} />
            </div>
            
            <div className="swarm-plots-container">
                <SwarmPlots swarmData={swarmData} />
            </div>
            
        </div>
    );
}

export default SwarmDesign;