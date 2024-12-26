import React from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // Prepare data for plotting
  const groupedData = {}; // To group drones by position slot (pos_id)
  drones.forEach((drone) => {
    if (!groupedData[drone.pos_id]) groupedData[drone.pos_id] = [];
    groupedData[drone.pos_id].push(drone);
  });

  // Preprocess data for plotting
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
      isDisabled: drone.isDisabled || false, // Indicate if the drone is disabled
      status: isPosMismatch ? "Mismatch" : "Correct", // Add status field
    };
  });

  // Marker Colors and Border Styles
  const markerColors = customData.map((data) =>
    data.isPosMismatch ? 'orange' : 'blue' // Color based on position mismatch
  );

  const markerBorderColors = customData.map((data) =>
    data.within_acceptable_range ? 'green' : 'red' // Border color based on deviation
  );

  // Adjust position to handle overlaps
  const xPlotValues = drones.map((drone) => {
    const overlapIndex = groupedData[drone.pos_id].findIndex(
      (d) => d.hw_id === drone.hw_id
    );
    return parseFloat(drone.y) + overlapIndex * 0.5; // Offset for overlapping markers
  });

  const yPlotValues = drones.map((drone) => {
    const overlapIndex = groupedData[drone.pos_id].findIndex(
      (d) => d.hw_id === drone.hw_id
    );
    return parseFloat(drone.x) + overlapIndex * 0.5; // Offset for overlapping markers
  });

  return (
    <Plot
      data={[
        {
          x: xPlotValues,
          y: yPlotValues,
          text: customData.map((data) => `${data.hw_id}`), // Show only HW ID
          customdata: customData,
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: 20,
            color: markerColors,
            opacity: 0.8,
            line: {
              color: markerBorderColors,
              width: 2,
            },
          },
          textfont: {
            color: 'white', // Use white for better contrast
            size: 10,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>North (X):</b> %{customdata.x}<br>' +
            '<b>East (Y):</b> %{customdata.y}<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}<br>' +
            '<b>Status:</b> %{customdata.status}<extra></extra>', // Use precomputed status field
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
        margin: {
          l: 50,
          r: 50,
          t: 50,
          b: 50,
        },
      }}
      onClick={(data) => {
        const clickedDroneHwId = data.points[0].customdata.hw_id;
        onDroneClick(clickedDroneHwId);
        const element = document.querySelector(
          `.drone-config-card[data-hw-id="${clickedDroneHwId}"]`
        );
        if (element) {
          element.scrollIntoView({ behavior: 'smooth' }); // Smooth scrolling
        }
      }}
    />
  );
}

export default InitialLaunchPlot;
