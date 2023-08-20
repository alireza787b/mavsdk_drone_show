import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick }) {
    const xValues = drones.map(drone => parseFloat(drone.x));
    const yValues = drones.map(drone => parseFloat(drone.y));
    const labels = drones.map(drone => drone.hw_id);

    return (
        <Plot
            data={[
                {
                    x: xValues,
                    y: yValues,
                    text: labels,
                    type: 'scatter',
                    mode: 'markers+text',
                    marker: {
                        size: 16,
                        color: '#3498db', // Bright blue
                        opacity: 0.8,
                        line: {
                            color: '#1A5276',  // Dark blue border
                            width: 2
                        }
                    },
                    textfont: {
                        color: 'white',
                        size: 14
                    },
                    textposition: 'center',
                    hoverinfo: 'x+y',  // Show X and Y coordinates on hover
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
                hoverlabel: {
                    font: {
                        color: 'white'
                    }
                }
            }}
            onClick={(data) => {
                const clickedIndex = data.points[0].pointIndex;
                const clickedDroneHwId = labels[clickedIndex];
                onDroneClick(clickedDroneHwId);
                document.querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`).scrollIntoView({ behavior: "smooth" });
            }}
        />
    );
}

export default InitialLaunchPlot;
