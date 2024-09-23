// app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.js

import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // Prepare data for plotting
  const xValues = drones.map((drone) => parseFloat(drone.x));
  const yValues = drones.map((drone) => parseFloat(drone.y));
  const labels = drones.map((drone) => drone.hw_id);

  const customData = drones.map((drone) => {
    const deviation = deviationData[drone.hw_id];
    return {
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
      x: parseFloat(drone.x),
      y: parseFloat(drone.y),
      deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
      deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
      total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
      within_acceptable_range: deviation?.within_acceptable_range,
    };
  });

  const markerColors = customData.map((data) => {
    if (data.within_acceptable_range === true) return 'green';
    if (data.within_acceptable_range === false) return 'red';
    return '#3498db'; // Default color if deviation data is unavailable
  });

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
            size: 30,
            color: markerColors,
            opacity: 0.8,
            line: {
              color: '#1A5276',
              width: 2,
            },
          },
          textfont: {
            color: 'white',
            size: 14,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>X:</b> %{customdata.x}<br>' +
            '<b>Y:</b> %{customdata.y}<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}<extra></extra>',
        },
      ]}
      layout={{
        title: 'Initial Launch Positions',
        xaxis: {
          title: 'East (X)',
          showgrid: true,
          zeroline: true,
        },
        yaxis: {
          title: 'North (Y)',
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
        document
          .querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`)
          ?.scrollIntoView({ behavior: 'smooth' });
      }}
    />
  );
}

export default InitialLaunchPlot;
