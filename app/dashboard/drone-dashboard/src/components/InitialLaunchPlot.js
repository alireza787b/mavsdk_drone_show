import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import { Alert, AlertDescription } from '@/components/ui/alert';

function InitialLaunchPlot({ 
  drones, 
  onDroneClick, 
  deviationData,
  maxAllowedDeviation = 0.5, // meters
  minSafeDistance = 2.0,     // meters between drones
}) {
  // Memoize processed drone data to avoid recalculations
  const {
    plotData,
    hasPositionIdMismatch,
    unsafeDroneDistances,
    duplicatePositionIds
  } = useMemo(() => {
    // Process and validate drone positions
    const dronesByPosition = new Map();
    const unsafePairs = [];
    
    const processedDrones = drones.map((drone) => {
      const deviation = deviationData[drone.hw_id] || {};
      const displayId = drone.pos_id || drone.hw_id;
      
      // Track drones by position ID for duplicate detection
      if (drone.pos_id) {
        if (dronesByPosition.has(drone.pos_id)) {
          duplicatePositionIds.push(drone.pos_id);
        }
        dronesByPosition.set(drone.pos_id, drone);
      }

      // Calculate distances between drones
      drones.forEach((otherDrone) => {
        if (drone.hw_id !== otherDrone.hw_id) {
          const distance = Math.sqrt(
            Math.pow(drone.x - otherDrone.x, 2) + 
            Math.pow(drone.y - otherDrone.y, 2)
          );
          if (distance < minSafeDistance) {
            unsafePairs.push({
              drone1: drone.hw_id,
              drone2: otherDrone.hw_id,
              distance
            });
          }
        }
      });

      return {
        x: parseFloat(drone.y), // East (Y)
        y: parseFloat(drone.x), // North (X)
        hw_id: drone.hw_id,
        pos_id: drone.pos_id,
        displayId,
        originalX: parseFloat(drone.x),
        originalY: parseFloat(drone.y),
        deviation_north: deviation.deviation_north?.toFixed(2) || 'N/A',
        deviation_east: deviation.deviation_east?.toFixed(2) || 'N/A',
        total_deviation: deviation.total_deviation?.toFixed(2) || 'N/A',
        within_acceptable_range: deviation.within_acceptable_range,
        markerColor: getMarkerColor(deviation, drone.pos_id !== null)
      };
    });

    return {
      plotData: processedDrones,
      hasPositionIdMismatch: drones.some(d => d.pos_id && d.pos_id !== d.hw_id),
      unsafeDroneDistances: unsafePairs,
      duplicatePositionIds: Array.from(new Set(duplicatePositionIds))
    };
  }, [drones, deviationData, maxAllowedDeviation, minSafeDistance]);

  // Helper function to determine marker color based on status
  const getMarkerColor = (deviation, hasPositionOverride) => {
    if (!deviation.within_acceptable_range && deviation.total_deviation > maxAllowedDeviation) {
      return 'red';    // Dangerous deviation
    }
    if (hasPositionOverride) {
      return '#FFA500'; // Orange for position overrides
    }
    if (deviation.within_acceptable_range) {
      return 'green';  // Good position
    }
    return '#3498db';  // Default blue
  };

  return (
    <div className="space-y-4">
      {/* Safety Alerts */}
      {hasPositionIdMismatch && (
        <Alert variant="warning">
          <AlertDescription>
            Position ID overrides are active! Some drones are operating in different positions than their hardware IDs.
          </AlertDescription>
        </Alert>
      )}
      
      {unsafeDroneDistances.length > 0 && (
        <Alert variant="destructive">
          <AlertDescription>
            Warning: Unsafe distances detected between drones:{' '}
            {unsafeDroneDistances.map(({drone1, drone2, distance}) => 
              `Drones ${drone1}-${drone2} (${distance.toFixed(1)}m)`
            ).join(', ')}
          </AlertDescription>
        </Alert>
      )}

      {duplicatePositionIds.length > 0 && (
        <Alert variant="destructive">
          <AlertDescription>
            Error: Duplicate position IDs detected: {duplicatePositionIds.join(', ')}
          </AlertDescription>
        </Alert>
      )}

      {/* Plot Component */}
      <Plot
        data={[{
          x: plotData.map(d => d.x),
          y: plotData.map(d => d.y),
          text: plotData.map(d => d.displayId),
          customdata: plotData,
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: 30,
            color: plotData.map(d => d.markerColor),
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
            '<b>Display ID:</b> %{customdata.displayId}<br>' +
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>North (X):</b> %{customdata.originalX}m<br>' +
            '<b>East (Y):</b> %{customdata.originalY}m<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}m<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}m<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}m<extra></extra>',
        }]}
        layout={{
          title: 'Initial Launch Positions',
          xaxis: {
            title: 'East (Y) - meters',
            showgrid: true,
            zeroline: true,
            gridcolor: '#e0e0e0',
          },
          yaxis: {
            title: 'North (X) - meters',
            showgrid: true,
            zeroline: true,
            gridcolor: '#e0e0e0',
          },
          hovermode: 'closest',
          plot_bgcolor: '#f7f7f7',
          paper_bgcolor: '#f7f7f7',
        }}
        onClick={(data) => {
          const clickedDrone = data.points[0].customdata;
          onDroneClick(clickedDrone.hw_id);
          document
            .querySelector(`.drone-config-card[data-hw-id="${clickedDrone.hw_id}"]`)
            ?.scrollIntoView({ behavior: 'smooth' });
        }}
      />
    </div>
  );
}

export default InitialLaunchPlot;