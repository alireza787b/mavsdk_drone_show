import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from './DroneGraph';

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
    const [swarmData, setSwarmData] = useState([]);
    const [configData, setConfigData] = useState([]);
    const { topLeaders, intermediateLeaders } = categorizeDrones(swarmData);
    const [selectedDroneId, setSelectedDroneId] = useState(null); // 1. Added state for selected drone ID
    
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

    return (

        <div className="swarm-design-container">

        <div className="swarm-container">
        
        {swarmData.length ? swarmData.map(drone => (
                    <div 
                        className={`swarm-drone-card ${drone.hw_id === selectedDroneId ? 'selected-drone' : ''} ${topLeaders.includes(drone) ? 'top-leader' : intermediateLeaders.includes(drone) ? 'intermediate-leader' : 'follower'}`} 
                        key={drone.hw_id}
                        onClick={() => handleDroneCardClick(drone.hw_id)} // Added onClick handler
                    >
                    <h3>Drone ID: {drone.hw_id}</h3>
                    <p>
                        {drone.follow === '0' ? 
                            <span className="role leader">Top Leader</span> : 
                            intermediateLeaders.includes(drone) ? 
                            <span className="role intermediate">Intermediate Leader (Follows Drone {drone.follow})</span> :
                            <span className="role follower">Follows Drone {drone.follow}</span>
                        }
                    </p>
                    {(topLeaders.includes(drone) || intermediateLeaders.includes(drone)) && (
                        <p>Followed by: {dronesFollowing(drone.hw_id).join(', ')}</p>
                    )}
                    <div className="collapsible-details">
                        <p><i className="position-icon"></i> Position Offset (m): North: {drone.offset_n}, East: {drone.offset_e}</p>
                        <p><i className="ip-icon"></i> Altitude Offset: {drone.offset_alt}</p>
                        {/* Add other properties as needed */}
                    </div>
                </div>
            )) : <p>No data available for swarm configuration.</p>}
        </div>
        <div className="swarm-graph-container">
        <DroneGraph swarmData={swarmData} onSelectDrone={setSelectedDroneId} />

        </div>
    </div>
    );
}

export default SwarmDesign;
