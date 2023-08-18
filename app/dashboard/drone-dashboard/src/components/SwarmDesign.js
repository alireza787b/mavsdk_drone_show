import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from './DroneGraph';
import SwarmPlots from './SwarmPlots';
import DroneCard from './DroneCard';



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

    const handleSaveChanges = (hw_id, updatedDroneData) => {
        setSwarmData(prevDrones => prevDrones.map(drone => drone.hw_id === hw_id ? updatedDroneData : drone));
    };

    
    const handleDroneCardClick = (droneId) => {
        setSelectedDroneId(droneId);
    };

    useEffect(() => {
        // Fetch swarm data
        const fetchSwarmData = axios.get('http://localhost:5000/get-swarm-data');
        // Fetch config data
        const fetchConfigData = axios.get('http://localhost:5000/get-config-data');
    
        Promise.all([fetchSwarmData, fetchConfigData])
            .then(([swarmResponse, configResponse]) => {
                setSwarmData(swarmResponse.data);
                setConfigData(configResponse.data);
            })
            .catch(error => {
                console.error("Error fetching data:", error);
            });
    
    }, []); // Empty dependency array ensures this runs once on component mount
    

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
    axios.get('http://localhost:5000/get-swarm-data')
        .then(response => {
            setSwarmData(response.data);
        })
        .catch(error => {
            console.error("Error fetching original swarm data:", error);
        });
};

const saveUpdatedSwarmData = () => {
    axios.post('http://localhost:5000/save-swarm-data', swarmData)
        .then(response => {
            if (response.status === 200) {
                alert(response.data.message);
            } else {
                alert('Error saving data.');
            }
        })
        .catch(error => {
            console.error("Error saving updated swarm data:", error);
            alert('Error saving data.');
        });
};

//console.log("Current Selected Drone:", selectedDroneId);

    return (
        <div className="swarm-design-container">
    
            <div className="control-buttons">
            <button className="save" onClick={handleSaveChangesToServer}>Save Changes</button>
                <button className="revert" onClick={handleRevertChanges}>Revert</button>
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
