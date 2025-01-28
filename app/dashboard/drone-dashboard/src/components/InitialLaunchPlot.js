import React, { useState } from 'react';
import Plot from 'react-plotly.js';

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // --------------------------------------------------------------------------
  // 1) State for Forward Heading (0° to 360°)
  // --------------------------------------------------------------------------
  const [forwardHeading, setForwardHeading] = useState(0);

  // --------------------------------------------------------------------------
  // 2) Group Drones by Position Slot to Handle Overlap
  // --------------------------------------------------------------------------
  const groupedData = {};
  drones.forEach((drone) => {
    if (!groupedData[drone.pos_id]) groupedData[drone.pos_id] = [];
    groupedData[drone.pos_id].push(drone);
  });

  // --------------------------------------------------------------------------
  // 3) Precompute Data with Deviation and Status
  // --------------------------------------------------------------------------
  const customData = drones.map((drone) => {
    const deviation = deviationData[drone.hw_id];
    const isPosMismatch = drone.hw_id !== drone.pos_id;
    return {
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
      // Original real-world coordinates (assuming X=North, Y=East):
      north: parseFloat(drone.x),
      east: parseFloat(drone.y),
      deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
      deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
      total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
      within_acceptable_range: deviation?.within_acceptable_range,
      isPosMismatch,
      isDisabled: drone.isDisabled || false,
      status: isPosMismatch ? "Mismatch" : "Correct",
    };
  });

  // --------------------------------------------------------------------------
  // 4) Configure Marker Colors (Fill & Border) Based on Conditions
  // --------------------------------------------------------------------------
  const markerColors = customData.map((d) =>
    d.isPosMismatch ? 'orange' : 'blue'
  );
  const markerBorderColors = customData.map((d) =>
    d.within_acceptable_range ? 'green' : 'red'
  );

  // --------------------------------------------------------------------------
  // 5) 2D Rotation Utility: Rotate (N, E) by heading (clockwise) then map to (X=North, Y=West)
  //    Heading is assumed to increase clockwise from North.
  //    After rotation, we invert E => W = -ERot, so Y axis shows West positively.
  // --------------------------------------------------------------------------
  function rotateToHeading(n, e, headingDeg) {
    const theta = (headingDeg * Math.PI) / 180.0;
    const cosT = Math.cos(theta);
    const sinT = Math.sin(theta);

    // Clockwise rotation by 'headingDeg' around the origin:
    // n' =  n*cos(θ) + e*sin(θ)
    // e' = -n*sin(θ) + e*cos(θ)
    // Then map e' -> w' = - e'
    const nRot = n * cosT + e * sinT;
    const eRot = -n * sinT + e * cosT;
    // Return X=North, Y=West
    return { xPlot: nRot, yPlot: -eRot };
  }

  // --------------------------------------------------------------------------
  // 6) Compute Plot (x, y) Values with Overlap Offsets & Rotation
  //    Overlap offset is applied before rotation, so each drone in the same slot
  //    is slightly shifted to avoid direct overlap.
  // --------------------------------------------------------------------------
  const xPlotValues = [];
  const yPlotValues = [];

  drones.forEach((drone) => {
    const overlapIndex = groupedData[drone.pos_id].findIndex(
      (d) => d.hw_id === drone.hw_id
    );

    // Base coordinates (North, East)
    const n = parseFloat(drone.x) + overlapIndex * 0.5;
    const e = parseFloat(drone.y) + overlapIndex * 0.5;

    // Rotate according to the current forward heading
    const { xPlot, yPlot } = rotateToHeading(n, e, forwardHeading);

    xPlotValues.push(xPlot);
    yPlotValues.push(yPlot);
  });

  // --------------------------------------------------------------------------
  // 7) Render
  //    - Slider for Forward Heading
  //    - Plotly Chart with Real-Time Rotation
  // --------------------------------------------------------------------------
  return (
    <div style={{ width: '100%', maxWidth: 900, margin: '0 auto' }}>
      {/* ---------------------------------------------------------------------
         Heading Slider
      --------------------------------------------------------------------- */}
      <div style={{ marginBottom: '1em', textAlign: 'center' }}>
        <label htmlFor="headingSlider" style={{ marginRight: 10 }}>
          Forward Heading: {forwardHeading}°
        </label>
        <input
          id="headingSlider"
          type="range"
          min={0}
          max={360}
          value={forwardHeading}
          onChange={(e) => setForwardHeading(parseInt(e.target.value, 10))}
          style={{ width: '60%' }}
        />
      </div>

      {/* ---------------------------------------------------------------------
         Drone Launch Positions Plot
      --------------------------------------------------------------------- */}
      <Plot
        data={[
          {
            x: xPlotValues,
            y: yPlotValues,
            text: customData.map((data) => `${data.hw_id}`),
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
              color: 'white',
              size: 10,
              family: 'Arial',
            },
            textposition: 'middle center',
            hovertemplate:
              '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
              '<b>Position ID:</b> %{customdata.pos_id}<br>' +
              '<br><b>Real North (X):</b> %{customdata.north}<br>' +
              '<b>Real East (Y):</b> %{customdata.east}<br>' +
              '<br><b>Plot X (Rotated North):</b> %{x:.2f}<br>' +
              '<b>Plot Y (Rotated West):</b> %{y:.2f}<br>' +
              '<br><b>Deviation North:</b> %{customdata.deviation_north}<br>' +
              '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
              '<b>Total Deviation:</b> %{customdata.total_deviation}<br>' +
              '<b>Status:</b> %{customdata.status}<extra></extra>',
          },
        ]}
        layout={{
          title: 'Initial Launch Positions',
          xaxis: {
            title: 'North (m)',
            showgrid: true,
            zeroline: true,
          },
          yaxis: {
            title: 'West (m)',
            showgrid: true,
            zeroline: true,
            // Flip Y if you want "West" increasing to the left or keep as-is to match typical plotting
            // autorange: 'reversed', 
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
            element.scrollIntoView({ behavior: 'smooth' });
          }
        }}
        style={{ width: '100%', height: '600px' }}
        config={{ responsive: true }}
      />
    </div>
  );
}

export default InitialLaunchPlot;
