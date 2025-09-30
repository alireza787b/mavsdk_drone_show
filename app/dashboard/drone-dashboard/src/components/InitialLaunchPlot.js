// src/components/InitialLaunchPlot.js
import React from 'react';
import Plot from 'react-plotly.js';
import { useTheme } from '../hooks/useTheme';

function InitialLaunchPlot({
  drones,
  onDroneClick,
  deviationData,
  forwardHeading = 0, // incoming heading from the parent
}) {
  const { isDark } = useTheme();

  // Theme-aware colors
  const themeColors = {
    background: isDark ? '#1a1a1a' : '#f8f9fa',
    paper: isDark ? '#1a1a1a' : '#f8f9fa',
    text: isDark ? '#e9ecef' : '#343a40',
    grid: isDark ? '#495057' : '#dee2e6',
    title: isDark ? '#f8f9fa' : '#212529',
    axisTitle: isDark ? '#adb5bd' : '#6c757d',
  };

  // --------------------------------------------------------------
  // Group drones by position (pos_id) for overlap offset
  // --------------------------------------------------------------
  const groupedData = {};
  drones.forEach((drone) => {
    if (!groupedData[drone.pos_id]) groupedData[drone.pos_id] = [];
    groupedData[drone.pos_id].push(drone);
  });

  // --------------------------------------------------------------
  // Precompute custom data with deviations & mismatch
  // --------------------------------------------------------------
  const customData = drones.map((drone) => {
    const deviation = deviationData[drone.hw_id];
    const isPosMismatch = drone.hw_id !== drone.pos_id;

    return {
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
      // Interpreting drone.x as "North," drone.y as "East":
      north: parseFloat(drone.x),
      east: parseFloat(drone.y),
      deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
      deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
      total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
      within_acceptable_range: deviation?.within_acceptable_range,
      isPosMismatch,
      isDisabled: drone.isDisabled || false,
      status: isPosMismatch ? 'Mismatch' : 'Correct',
    };
  });

  // Marker colors (fill) & borders
  const markerColors = customData.map((d) => (d.isPosMismatch ? 'orange' : 'blue'));
  const markerBorderColors = customData.map((d) =>
    d.within_acceptable_range ? 'green' : 'red'
  );

  // --------------------------------------------------------------
  // Rotation function (clockwise)
  //   heading in degrees, standard math rotation is CCW => we use -θ for CW
  // --------------------------------------------------------------
  function rotateCW(x, y, headingDeg) {
    const theta = (-headingDeg * Math.PI) / 180; // negative for clockwise
    const cosT = Math.cos(theta);
    const sinT = Math.sin(theta);
    // standard 2D rotation about origin: (x cosθ - y sinθ, x sinθ + y cosθ)
    const xRot = x * cosT - y * sinT;
    const yRot = x * sinT + y * cosT;
    return { xRot, yRot };
  }

  // --------------------------------------------------------------
  // Compute final plot (x,y) by:
  //   1) Overlap offset
  //   2) Pre-transform: X_pre = east, Y_pre = north (no negation for east)
  //   3) Rotate clockwise by heading
  // --------------------------------------------------------------
  const xPlotValues = [];
  const yPlotValues = [];

  drones.forEach((drone) => {
    const overlapIndex = groupedData[drone.pos_id].findIndex(
      (d) => d.hw_id === drone.hw_id
    );

    // Original "north"/"east" (already in NED format)
    const n = parseFloat(drone.x);  // North
    const e = parseFloat(drone.y);  // East

    // Overlap offset: push each subsequent drone in the same pos_id
    // a little in both n/e to avoid markers stacking exactly
    const nOffset = n + overlapIndex * 0.3;
    const eOffset = e + overlapIndex * 0.3;

    // Pre-transform: X_pre = east, Y_pre = north (no negation for east)
    const X_pre = eOffset; // East remains as East
    const Y_pre = nOffset; // North remains as North

    // Rotate clockwise by forwardHeading
    const { xRot, yRot } = rotateCW(X_pre, Y_pre, forwardHeading);

    xPlotValues.push(xRot);
    yPlotValues.push(yRot);
  });

  // --------------------------------------------------------------
  // Render Plot
  // --------------------------------------------------------------
  return (
    <Plot
      data={[
        {
          x: xPlotValues,
          y: yPlotValues,
          text: customData.map((d) => d.hw_id),
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
            color: isDark ? '#ffffff' : '#000000',
            size: 10,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>North (raw x):</b> %{customdata.north}<br>' +
            '<b>East (raw y):</b> %{customdata.east}<br>' +
            '<b>Xᵣₒₜ (plot):</b> %{x:.2f}<br>' +
            '<b>Yᵣₒₜ (plot):</b> %{y:.2f}<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}<br>' +
            '<b>Status:</b> %{customdata.status}<extra></extra>',
        },
      ]}
      layout={{
        title: {
          text: `Initial Launch Positions (Heading = ${forwardHeading}°)`,
          font: {
            color: themeColors.title,
            size: 16,
          },
        },
        xaxis: {
          title: {
            text: '← West  |  East →',
            font: {
              color: themeColors.axisTitle,
            },
          },
          showgrid: true,
          zeroline: true,
          gridcolor: themeColors.grid,
          tickfont: {
            color: themeColors.text,
          },
        },
        yaxis: {
          title: {
            text: '← South | North →',
            font: {
              color: themeColors.axisTitle,
            },
          },
          showgrid: true,
          zeroline: true,
          gridcolor: themeColors.grid,
          tickfont: {
            color: themeColors.text,
          },
        },
        hovermode: 'closest',
        plot_bgcolor: themeColors.background,
        paper_bgcolor: themeColors.paper,
        font: {
          color: themeColors.text,
        },
        margin: {
          l: 60,
          r: 40,
          t: 60,
          b: 60,
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
      style={{ width: '100%', height: '500px' }}
      config={{ responsive: true }}
    />
  );
}

export default InitialLaunchPlot;
