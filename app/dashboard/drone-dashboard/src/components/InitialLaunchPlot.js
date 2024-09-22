import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick }) {
    const xValues = drones.map(drone => parseFloat(drone.x));
    const yValues = drones.map(drone => parseFloat(drone.y));
    const labels = drones.map(drone => `Pos ${drone.pos_id}: HW ${drone.hw_id}`);
    const customData = drones.map(drone => ({ hw_id: drone.hw_id, pos_id: drone.pos_id }));

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
                        '<b>Position ID:</b> %{customdata.pos_id}<br>' +
                        '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
                        '<b>X:</b> %{x}<br>' +
                        '<b>Y:</b> %{y}<extra></extra>',
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
                document.querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`).scrollIntoView({ behavior: "smooth" });
            }}
        />
    );
}

export default InitialLaunchPlot;
