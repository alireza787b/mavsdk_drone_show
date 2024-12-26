import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // Prepare data for plotting
  const xValues = drones.map((drone) => parseFloat(drone.x)); // North (X)
  const yValues = drones.map((drone) => parseFloat(drone.y)); // East (Y)

  const customData = drones.map((drone) => {
    const deviation = deviationData[drone.hw_id];
    const isPosMismatch = drone.hw_id !== drone.pos_id; // Check for position mismatch
    return {
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
      x: parseFloat(drone.x),
      y: parseFloat(drone.y),
      deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
      deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
      total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
      within_acceptable_range: deviation?.within_acceptable_range,
      isPosMismatch,
    };
  });

  // Marker Colors and Border Styles
  const markerColors = customData.map((data) => {
    if (data.within_acceptable_range === false) return 'red'; // Too much deviation
    if (data.isPosMismatch) return 'orange'; // Position mismatch
    return 'green'; // Normal
  });

  const markerBorderColors = customData.map((data) =>
    data.within_acceptable_range ? 'green' : 'red'
  );

  const xPlotValues = yValues; // East (Y)
  const yPlotValues = xValues; // North (X)

  return (
    <Plot
      data={[
        {
          x: xPlotValues,
          y: yPlotValues,
          text: customData.map(
            (data) => `HW: ${data.hw_id}, POS: ${data.pos_id}`
          ),
          customdata: customData,
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: 30,
            color: markerColors,
            opacity: 0.8,
            line: {
              color: markerBorderColors,
              width: 3,
            },
          },
          textfont: {
            color: 'black',
            size: 12,
            family: 'Arial',
          },
          textposition: 'top center',
          hovertemplate:
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>North (X):</b> %{customdata.x}<br>' +
            '<b>East (Y):</b> %{customdata.y}<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}<br>' +
            '<b>Mismatch:</b> %{customdata.isPosMismatch}<extra></extra>',
        },
      ]}
      layout={{
        title: 'Initial Launch Positions',
        xaxis: {
          title: 'East (Y)',
          showgrid: true,
          zeroline: true,
        },
        yaxis: {
          title: 'North (X)',
          showgrid: true,
          zeroline: true,
        },
        hovermode: 'closest',
        plot_bgcolor: '#f7f7f7',
        paper_bgcolor: '#f7f7f7',
        legend: {
          orientation: 'h',
          x: 0.5,
          y: -0.2,
          xanchor: 'center',
        },
      }}
      onClick={(data) => {
        const clickedDroneHwId = data.points[0].customdata.hw_id;
        onDroneClick(clickedDroneHwId);
        document
          .querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`)
          ?.scrollIntoView({ behavior: 'smooth' });
      }}
    />
  );
}

export default InitialLaunchPlot;
