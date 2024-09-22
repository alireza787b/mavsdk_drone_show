//app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.js
import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick }) {
    // Prepare data for plotting based on pos_id
    const xValues = drones.map(drone => parseFloat(drone.x));
    const yValues = drones.map(drone => parseFloat(drone.y));
    const labels = drones.map(drone => drone.hw_id);
    const customData = drones.map(drone => ({
        hw_id: drone.hw_id,
        pos_id: drone.pos_id,
        x: parseFloat(drone.x),
        y: parseFloat(drone.y),
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
                        size: 30, // Increased size for better visibility
                        color: '#3498db',
                        opacity: 0.8,
                        line: {
                            color: '#1A5276',
                            width: 2
                        }
                    },
                    textfont: {
                        color: 'white',
                        size: 14,
                        family: 'Arial'
                    },
                    textposition: 'middle center', // Center the text inside markers
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
                    showgrid: true,
                    zeroline: true,
                },
                yaxis: {
                    title: 'East (Y)',
                    showgrid: true,
                    zeroline: true,
                },
                hovermode: 'closest',
                plot_bgcolor: '#f7f7f7',
                paper_bgcolor: '#f7f7f7',
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
