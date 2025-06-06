//app/dashboard/drone-dashboard/src/components/SwarmPlots.js
import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';

import '../styles/SwarmPlots.css';


function ThreeDPlot({ data, swarmData }) {
    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            z: data.map(d => d.z),
            mode: 'markers+text',
            marker: {
                size: 15,
                color: data.map(d => {
                    if (d.follow === '0') return '#4caf50';  // Color for top leaders
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return '#ffcc00';  // Color for followers
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return '#2196f3';  // Color for intermediate leaders
                    else return '#ffcc00';  // Default color for followers
                }),
                opacity: 0.9,
            },
            type: 'scatter3d',
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: 'white', 
                size: 16,  // Increased font size
                family: 'Arial, sans-serif',
                weight: 'bold'  // Bold font
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return 'Top Leader';
                return `Follows Drone ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];
    

    const layout = {
        margin: {
            l: 0,
            r: 0,
            b: 0,
            t: 0
        },
        scene: { 
            xaxis: {
                title: 'East'
            },
            yaxis: {
                title: 'North'
            },
            zaxis: {
                title: 'Altitude'
            }
        }
    };

    return <Plot data={plotData} layout={layout} />;
}


function NorthEastPlot({ data, swarmData }) {
    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            mode: 'markers+text',
            marker: {
                size: 20,
                color: data.map(d => {
                    if (d.follow === '0') return '#4caf50'; 
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return '#ffcc00';  
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return '#2196f3'; 
                    else return '#ffcc00'; 
                }),
                opacity: 0.9,
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: 'white', 
                size: 16,  
                family: 'Arial, sans-serif',
                weight: 'bold'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return 'Top Leader';
                return `Follows Drone ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        xaxis: {
            title: 'East'
        },
        yaxis: {
            title: 'North'
        },
        hovermode: 'closest'  // Important for synchronized hovering
    };

    return <Plot data={plotData} layout={layout} />;
}


function EastAltitudePlot({ data, swarmData }) {
    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            mode: 'markers+text',
            marker: {
                size: 20,
                color: data.map(d => {
                    if (d.follow === '0') return '#4caf50'; 
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return '#ffcc00';  
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return '#2196f3'; 
                    else return '#ffcc00'; 
                }),
                opacity: 0.9,
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: 'white', 
                size: 16,  
                family: 'Arial, sans-serif',
                weight: 'bold'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return 'Top Leader';
                return `Follows Drone ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        xaxis: {
            title: 'East'
        },
        yaxis: {
            title: 'Altitude'
        },
        hovermode: 'closest'  // Important for synchronized hovering
    };

    return <Plot data={plotData} layout={layout} />;
}

function NorthAltitudePlot({ data, swarmData }) {
    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            mode: 'markers+text',
            marker: {
                size: 20,
                color: data.map(d => {
                    if (d.follow === '0') return '#4caf50'; 
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return '#ffcc00';  
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return '#2196f3'; 
                    else return '#ffcc00'; 
                }),
                opacity: 0.9,
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: 'white', 
                size: 16,  
                family: 'Arial, sans-serif',
                weight: 'bold'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return 'Top Leader';
                return `Follows Drone ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        xaxis: {
            title: 'North'
        },
        yaxis: {
            title: 'Altitude'
        },
        hovermode: 'closest'  // Important for synchronized hovering
    };

    return <Plot data={plotData} layout={layout} />;
}


function SwarmPlots({ swarmData }) {
    const [selectedCluster, setSelectedCluster] = useState(undefined);
    const [processedData, setProcessedData] = useState([]);

    const leaders = swarmData.filter(drone =>
        drone.follow === '0' || swarmData.some(d => d.follow === drone.hw_id)
    );

    const getCumulativeOffset = (drone) => {
        if (drone.follow === '0') {
            return {
                x: 0,
                y: 0,
                z: 0,
                heading: 0  // Assume heading is zero for top leaders
            };
        } else {
            const leader = swarmData.find(d => d.hw_id === drone.follow);
            const leaderOffset = getCumulativeOffset(leader);

            // Parse offsets
            let offset_n = parseFloat(drone.offset_n);
            let offset_e = parseFloat(drone.offset_e);
            let offset_alt = parseFloat(drone.offset_alt);

            if (drone.body_coord === '1') {
                // Convert body coordinates to NEA (assuming leader heading is zero)
                const theta = leaderOffset.heading * Math.PI / 180; // Convert heading to radians
                const cosTheta = Math.cos(theta);
                const sinTheta = Math.sin(theta);

                // Rotate the offsets
                const rotated_n = offset_n * cosTheta - offset_e * sinTheta;
                const rotated_e = offset_n * sinTheta + offset_e * cosTheta;

                offset_n = rotated_n;
                offset_e = rotated_e;
            }

            return {
                x: leaderOffset.x + offset_e,
                y: leaderOffset.y + offset_n,
                z: leaderOffset.z + offset_alt,
                heading: leaderOffset.heading  // Propagate heading
            };
        }
    };

    const processSwarmData = (selectedLeaderId) => {
        const selectedLeader = swarmData.find(drone => drone.hw_id === selectedLeaderId);

        // Position the selected leader at the origin
        let processed = [{ ...selectedLeader, x: 0, y: 0, z: 0 }];

        swarmData.forEach(drone => {
            if (drone.hw_id !== selectedLeaderId) {
                const position = getCumulativeOffset(drone);
                processed.push({
                    ...drone,
                    x: position.x,
                    y: position.y,
                    z: position.z
                });
            }
        });

        setProcessedData(processed);
    };

    useEffect(() => {
        console.log("Swarm data updated:", swarmData);
    }, [swarmData]);

    useEffect(() => {
        if (swarmData.length) {
            const leadersList = swarmData.filter(drone =>
                drone.follow === '0' || swarmData.some(d => d.follow === drone.hw_id)
            );

            if (leadersList.length) {
                setSelectedCluster(leadersList[0]?.hw_id);
            }
        }
    }, [swarmData]);

    useEffect(() => {
        if (selectedCluster) {
            processSwarmData(selectedCluster);
        }
    }, [selectedCluster]);

    return (
        <div className="swarm-plots-container">
            <div className="cluster-selection">
                <label>Select Cluster: </label>
                <select
                    value={selectedCluster || ''}
                    onChange={e => setSelectedCluster(e.target.value)}
                >
                    {leaders.map(leader => (
                        <option key={leader.hw_id} value={leader.hw_id}>
                            {leader.hw_id} - {leader.follow === '0' ? 'Top Leader' : 'Intermediate Leader'}
                        </option>
                    ))}
                </select>
            </div>
            <div>
                <ThreeDPlot data={processedData} swarmData={swarmData} />
                <NorthEastPlot data={processedData} swarmData={swarmData} />
                <EastAltitudePlot data={processedData} swarmData={swarmData} />
                <NorthAltitudePlot data={processedData} swarmData={swarmData} />
            </div>
        </div>
    );
}

export default SwarmPlots;