// app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.js

import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import PropTypes from 'prop-types';

// Constants for marker colors
const COLORS = {
  NORMAL_FILL: '#3498db',       // Blue for normal assignments
  SUBSTITUTE_FILL: '#f39c12',   // Orange for substitutions
  INACTIVE_FILL: '#e74c3c',     // Red for inactive drones
  UNASSIGNED_FILL: '#95a5a6',   // Grey for unassigned positions
  NORMAL_BORDER: '#1A5276',     // Standard border color
  SUBSTITUTE_BORDER: '#d35400', // Darker orange for substitutions
  INACTIVE_BORDER: '#c0392b',   // Darker red for inactive drones
};

// Size and offset configurations
const MARKER_SIZE = 30;
const OFFSET = 5; // Offset in plotting units to separate overlapping drones

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // Prepare data using useMemo for performance optimization
  const plotData = useMemo(() => {
    const posIdMap = {}; // Map pos_id to array of drones
    drones.forEach((drone) => {
      if (posIdMap[drone.pos_id]) {
        posIdMap[drone.pos_id].push(drone);
      } else {
        posIdMap[drone.pos_id] = [drone];
      }
    });

    const plotPoints = [];
    const conflictPosIds = new Set();

    // Detect conflicts where multiple drones are assigned to the same pos_id
    Object.keys(posIdMap).forEach((posId) => {
      const assignedDrones = posIdMap[posId];
      if (assignedDrones.length > 1) {
        conflictPosIds.add(parseInt(posId, 10));
      }

      assignedDrones.forEach((drone, index) => {
        const deviation = deviationData[drone.hw_id];
        const isSubstitute = drone.pos_id !== drone.hw_id;
        const withinRange = deviation?.within_acceptable_range;

        // Determine marker colors based on status
        let fillColor = COLORS.NORMAL_FILL;
        let borderColor = COLORS.NORMAL_BORDER;

        if (isSubstitute) {
          fillColor = COLORS.SUBSTITUTE_FILL;
          borderColor = COLORS.SUBSTITUTE_BORDER;
        }

        if (withinRange === false || conflictPosIds.has(parseInt(posId, 10))) {
          fillColor = COLORS.INACTIVE_FILL;
          borderColor = COLORS.INACTIVE_BORDER;
        }

        // Calculate offset for multiple drones on the same position
        const totalDrones = assignedDrones.length;
        const angle = (index / totalDrones) * 2 * Math.PI;
        const xOffset = OFFSET * Math.cos(angle);
        const yOffset = OFFSET * Math.sin(angle);

        plotPoints.push({
          hw_id: drone.hw_id,
          pos_id: drone.pos_id,
          x: parseFloat(drone.x) + yOffset, // East (Y) with offset
          y: parseFloat(drone.y) + xOffset, // North (X) with offset
          deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
          deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
          total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
          within_acceptable_range: deviation?.within_acceptable_range,
          isSubstitute,
          isConflict: conflictPosIds.has(parseInt(posId, 10)),
          fillColor,
          borderColor,
        });
      });
    });

    // Identify unassigned positions
    const existingPosIds = new Set(drones.map((drone) => drone.pos_id));
    const totalPositions = 10; // Adjust based on operational setup

    for (let pos = 1; pos <= totalPositions; pos++) {
      if (!existingPosIds.has(pos)) {
        plotPoints.push({
          hw_id: null,
          pos_id: pos,
          x: null,
          y: null,
          deviation_north: 'N/A',
          deviation_east: 'N/A',
          total_deviation: 'N/A',
          within_acceptable_range: null,
          isSubstitute: false,
          isConflict: false,
          fillColor: COLORS.UNASSIGNED_FILL,
          borderColor: COLORS.NORMAL_BORDER,
        });
      }
    }

    return plotPoints;
  }, [drones, deviationData]);

  // Separate assigned and unassigned drones for plotting
  const assignedPoints = plotData.filter((point) => point.hw_id !== null);
  const unassignedPoints = plotData.filter((point) => point.hw_id === null);

  return (
    <Plot
      data={[
        // Assigned Drones
        {
          x: assignedPoints.map((p) => p.x), // North (X)
          y: assignedPoints.map((p) => p.y), // East (Y)
          text: assignedPoints.map((p) =>
            p.isSubstitute
              ? `Substitute: HW ID ${p.hw_id}`
              : `HW ID: ${p.hw_id}`
          ),
          customdata: assignedPoints,
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: MARKER_SIZE,
            color: assignedPoints.map((p) => p.fillColor),
            line: {
              color: assignedPoints.map((p) => p.borderColor),
              width: 3,
            },
            symbol: 'circle',
            opacity: 0.9,
          },
          textfont: {
            color: 'white',
            size: 12,
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
            '<b>Substitute:</b> %{customdata.isSubstitute}<br>' +
            '<b>Within Acceptable Range:</b> %{customdata.within_acceptable_range}<br>' +
            '<b>Conflict:</b> %{customdata.isConflict}<extra></extra>',
        },
        // Unassigned Positions
        {
          x: unassignedPoints.map((p) => p.x), // North (X) - null
          y: unassignedPoints.map((p) => p.y), // East (Y) - null
          text: unassignedPoints.map((p) => `Unassigned Position: ${p.pos_id}`),
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: MARKER_SIZE,
            color: unassignedPoints.map((p) => p.fillColor),
            line: {
              color: unassignedPoints.map((p) => p.borderColor),
              width: 2,
            },
            symbol: 'circle-open',
            opacity: 0.6,
          },
          textfont: {
            color: '#7f8c8d',
            size: 12,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Position ID:</b> %{text}<br>' +
            '<b>Status:</b> Unassigned<extra></extra>',
        },
      ]}
      layout={{
        title: 'Initial Launch Positions',
        xaxis: {
          title: 'North (X)',
          showgrid: true,
          zeroline: true,
          range: [-100, 100], // Adjust based on your operational area
          zerolinecolor: '#d3d3d3',
        },
        yaxis: {
          title: 'East (Y)',
          showgrid: true,
          zeroline: true,
          range: [-100, 100], // Adjust based on your operational area
          zerolinecolor: '#d3d3d3',
        },
        hovermode: 'closest',
        plot_bgcolor: '#f7f7f7',
        paper_bgcolor: '#f7f7f7',
        legend: {
          itemsizing: 'constant',
          orientation: 'h',
          y: -0.2,
        },
        // Optional: Add grid lines or shapes to represent positions
        shapes: [
          // Example: Add a grid or specific markers if needed
        ],
        annotations: [
          // Example: Add annotations or labels if needed
        ],
      }}
      config={{
        responsive: true,
        displayModeBar: false, // Hide the mode bar for a cleaner UI
        staticPlot: true, // Disable interactions like zoom for better clarity
      }}
      onClick={(data) => {
        if (data.points.length === 0) return;
        const clickedPoint = data.points[0];
        if (!clickedPoint.customdata || !clickedPoint.customdata.hw_id) return;

        const clickedDroneHwId = clickedPoint.customdata.hw_id;
        onDroneClick(clickedDroneHwId);

        // Smooth scroll to the drone config card
        const droneConfigCard = document.querySelector(
          `.drone-config-card[data-hw-id="${clickedDroneHwId}"]`
        );
        if (droneConfigCard) {
          droneConfigCard.scrollIntoView({ behavior: 'smooth' });
        }
      }}
    />
  );
}

InitialLaunchPlot.propTypes = {
  drones: PropTypes.arrayOf(
    PropTypes.shape({
      hw_id: PropTypes.number.isRequired,
      pos_id: PropTypes.number.isRequired,
      x: PropTypes.string.isRequired,
      y: PropTypes.string.isRequired,
    })
  ).isRequired,
  onDroneClick: PropTypes.func.isRequired,
  deviationData: PropTypes.objectOf(
    PropTypes.shape({
      deviation_north: PropTypes.number,
      deviation_east: PropTypes.number,
      total_deviation: PropTypes.number,
      within_acceptable_range: PropTypes.bool,
    })
  ).isRequired,
};

export default InitialLaunchPlot;
