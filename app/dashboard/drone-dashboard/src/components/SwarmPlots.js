//app/dashboard/drone-dashboard/src/components/SwarmPlots.js
import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';

import '../styles/SwarmPlots.css';

// Theme-aware color scheme
const getThemeColors = () => {
    const rootStyles = getComputedStyle(document.documentElement);
    return {
        bg: rootStyles.getPropertyValue('--color-bg-primary').trim(),
        paper: rootStyles.getPropertyValue('--color-bg-secondary').trim(),
        text: rootStyles.getPropertyValue('--color-text-primary').trim(),
        grid: rootStyles.getPropertyValue('--color-border-primary').trim(),
        primary: rootStyles.getPropertyValue('--color-primary').trim(),
        success: rootStyles.getPropertyValue('--color-success').trim(),
        warning: rootStyles.getPropertyValue('--color-warning').trim(),
        info: rootStyles.getPropertyValue('--color-info').trim(),
    };
};

// Theme-aware plot layout
const getBaseLayout = (colors, is3D = false) => ({
    plot_bgcolor: colors.bg,
    paper_bgcolor: colors.bg,
    font: {
        color: colors.text,
        family: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
        size: 11
    },
    margin: { l: 50, r: 20, t: 20, b: 50 },
    showlegend: false,
    autosize: true,
    responsive: true,
    xaxis: {
        gridcolor: colors.grid,
        zerolinecolor: colors.grid,
        tickfont: { color: colors.text, size: 10 },
        titlefont: { color: colors.text, size: 12 }
    },
    yaxis: {
        gridcolor: colors.grid,
        zerolinecolor: colors.grid,
        tickfont: { color: colors.text, size: 10 },
        titlefont: { color: colors.text, size: 12 }
    }
});

// Plot configuration for responsive behavior
const plotConfig = {
    responsive: true,
    displayModeBar: false,
    staticPlot: false,
    scrollZoom: false
};


function ThreeDPlot({ data, swarmData }) {
    const colors = getThemeColors();

    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            z: data.map(d => d.z),
            mode: 'markers+text',
            marker: {
                size: 12,
                color: data.map(d => {
                    if (d.follow === '0') return colors.success;
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return colors.warning;
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return colors.info;
                    else return colors.warning;
                }),
                opacity: 0.8,
                line: { color: colors.text, width: 1 }
            },
            type: 'scatter3d',
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: colors.text,
                size: 10,
                family: 'Inter, sans-serif'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return `Top Leader: ${d.hw_id}`;
                return `Drone ${d.hw_id} → Follows ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        ...getBaseLayout(colors, true),
        scene: {
            bgcolor: colors.bg,
            camera: { eye: { x: 1.5, y: 1.5, z: 1.5 } },
            xaxis: {
                title: { text: 'East (m)', font: { color: colors.text, size: 11 } },
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 9 }
            },
            yaxis: {
                title: { text: 'North (m)', font: { color: colors.text, size: 11 } },
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 9 }
            },
            zaxis: {
                title: { text: 'Altitude (m)', font: { color: colors.text, size: 11 } },
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 9 }
            }
        }
    };

    return (
        <div className="plot-wrapper plot-3d">
            <div className="plot-title">3D Formation View</div>
            <div className="plot-content">
                <Plot
                    data={plotData}
                    layout={layout}
                    config={plotConfig}
                    style={{ width: '100%', height: '100%' }}
                    useResizeHandler={true}
                />
            </div>
        </div>
    );
}


function NorthEastPlot({ data, swarmData }) {
    const colors = getThemeColors();

    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.y),
            mode: 'markers+text',
            marker: {
                size: 14,
                color: data.map(d => {
                    if (d.follow === '0') return colors.success;
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return colors.warning;
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return colors.info;
                    else return colors.warning;
                }),
                opacity: 0.8,
                line: { color: colors.text, width: 1 }
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: colors.text,
                size: 9,
                family: 'Inter, sans-serif'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return `Top Leader: ${d.hw_id}`;
                return `Drone ${d.hw_id} → Follows ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        ...getBaseLayout(colors),
        xaxis: {
            ...getBaseLayout(colors).xaxis,
            title: { text: 'East (m)', font: { color: colors.text, size: 12 } }
        },
        yaxis: {
            ...getBaseLayout(colors).yaxis,
            title: { text: 'North (m)', font: { color: colors.text, size: 12 } }
        },
        hovermode: 'closest'
    };

    return (
        <div className="plot-wrapper">
            <div className="plot-title">North-East View</div>
            <div className="plot-content">
                <Plot
                    data={plotData}
                    layout={layout}
                    config={plotConfig}
                    style={{ width: '100%', height: '100%' }}
                    useResizeHandler={true}
                />
            </div>
        </div>
    );
}


function EastAltitudePlot({ data, swarmData }) {
    const colors = getThemeColors();

    const plotData = [
        {
            x: data.map(d => d.x),
            y: data.map(d => d.z),
            mode: 'markers+text',
            marker: {
                size: 14,
                color: data.map(d => {
                    if (d.follow === '0') return colors.success;
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return colors.warning;
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return colors.info;
                    else return colors.warning;
                }),
                opacity: 0.8,
                line: { color: colors.text, width: 1 }
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: colors.text,
                size: 9,
                family: 'Inter, sans-serif'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return `Top Leader: ${d.hw_id}`;
                return `Drone ${d.hw_id} → Follows ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        ...getBaseLayout(colors),
        xaxis: {
            ...getBaseLayout(colors).xaxis,
            title: { text: 'East (m)', font: { color: colors.text, size: 12 } }
        },
        yaxis: {
            ...getBaseLayout(colors).yaxis,
            title: { text: 'Altitude (m)', font: { color: colors.text, size: 12 } }
        },
        hovermode: 'closest'
    };

    return (
        <div className="plot-wrapper">
            <div className="plot-title">East-Altitude View</div>
            <div className="plot-content">
                <Plot
                    data={plotData}
                    layout={layout}
                    config={plotConfig}
                    style={{ width: '100%', height: '100%' }}
                    useResizeHandler={true}
                />
            </div>
        </div>
    );
}

function NorthAltitudePlot({ data, swarmData }) {
    const colors = getThemeColors();

    const plotData = [
        {
            x: data.map(d => d.y),
            y: data.map(d => d.z),
            mode: 'markers+text',
            marker: {
                size: 14,
                color: data.map(d => {
                    if (d.follow === '0') return colors.success;
                    else if (swarmData.some(drone => drone.follow === d.hw_id) && d.follow !== '0') return colors.warning;
                    else if (swarmData.some(drone => drone.hw_id === d.follow)) return colors.info;
                    else return colors.warning;
                }),
                opacity: 0.8,
                line: { color: colors.text, width: 1 }
            },
            text: data.map(d => d.hw_id.toString()),
            textposition: 'middle center',
            textfont: {
                color: colors.text,
                size: 9,
                family: 'Inter, sans-serif'
            },
            hovertext: data.map(d => {
                if (d.follow === '0') return `Top Leader: ${d.hw_id}`;
                return `Drone ${d.hw_id} → Follows ${d.follow}`;
            }),
            hoverinfo: 'text',
        }
    ];

    const layout = {
        ...getBaseLayout(colors),
        xaxis: {
            ...getBaseLayout(colors).xaxis,
            title: { text: 'North (m)', font: { color: colors.text, size: 12 } }
        },
        yaxis: {
            ...getBaseLayout(colors).yaxis,
            title: { text: 'Altitude (m)', font: { color: colors.text, size: 12 } }
        },
        hovermode: 'closest'
    };

    return (
        <div className="plot-wrapper">
            <div className="plot-title">North-Altitude View</div>
            <div className="plot-content">
                <Plot
                    data={plotData}
                    layout={layout}
                    config={plotConfig}
                    style={{ width: '100%', height: '100%' }}
                    useResizeHandler={true}
                />
            </div>
        </div>
    );
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
            <div className="plots-grid">
                <ThreeDPlot data={processedData} swarmData={swarmData} />
                <NorthEastPlot data={processedData} swarmData={swarmData} />
                <EastAltitudePlot data={processedData} swarmData={swarmData} />
                <NorthAltitudePlot data={processedData} swarmData={swarmData} />
            </div>
        </div>
    );
}

export default SwarmPlots;