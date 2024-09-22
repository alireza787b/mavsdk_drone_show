//app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.js
import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick }) {
    // Create a mapping from pos_id to position (x, y)
    const posIdToPosition = {};
    drones.forEach(drone => {
        const posId = drone.pos_id;
        // Use the position associated with the pos_id
        if (!posIdToPosition[posId]) {
            posIdToPosition[posId] = {
                x: parseFloat(drone.x),
                y: parseFloat(drone.y)
            };
        }
    });

    // Prepare data for plotting
    const xValues = drones.map(drone => posIdToPosition[drone.pos_id].x);
    const yValues = drones.map(drone => posIdToPosition[drone.pos_id].y);
    const labels = drones.map(drone => `HW ${drone.hw_id}`);
    const customData = drones.map(drone => ({
        hw_id: drone.hw_id,
        pos_id: drone.pos_id,
        x: posIdToPosition[drone.pos_id].x,
        y: posIdToPosition[drone.pos_id].y
    }));

    return (
        <Plot
            data={[
                {
                    x: xValues,
                    y: yValues,
                    text: labels,
                    customdata: customData,
                    type: 'scatter',
                    mode: 'markers+text',
                    marker: {
                        size: 16,
                        color: '#3498db',
                        opacity: 0.8,
                        line: {
                            color: '#1A5276',
                            width: 2
                        }
                    },
                    textfont: {
                        color: 'white',
                        size: 12
                    },
                    textposition: 'top center',
                    hovertemplate:
                        '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
                        '<b>Position ID:</b> %{customdata.pos_id}<br>' +
                        '<b>X:</b> %{customdata.x}<br>' +
                        '<b>Y:</b> %{customdata.y}<extra></extra>',
                }
            ]}
            layout={{
                title: 'Initial Launch Positions',
                xaxis: {
                    title: 'North (X)',
                },
                yaxis: {
                    title: 'East (Y)',
                },
                hovermode: 'closest',
            }}
            onClick={(data) => {
                const clickedDroneHwId = data.points[0].customdata.hw_id;
                onDroneClick(clickedDroneHwId);
                document.querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`)?.scrollIntoView({ behavior: "smooth" });
            }}
        />
    );
}

export default InitialLaunchPlot;
