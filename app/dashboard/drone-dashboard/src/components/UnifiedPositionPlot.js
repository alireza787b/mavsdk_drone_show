// src/components/UnifiedPositionPlot.js

import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { useTheme } from '../hooks/useTheme';
import '../styles/UnifiedPositionPlot.css';

/**
 * UnifiedPositionPlot - Unified drone position visualization
 *
 * Shows drone positions from trajectory CSV files with optional deviation display.
 * Features:
 * - Expected positions (from trajectory CSV - single source of truth)
 * - Optional actual positions and deviation vectors (toggle via checkbox)
 * - Auto-refresh for live monitoring
 * - Status-based color coding
 * - Clean, professional UI/UX
 *
 * @param {Array} drones - Drone configuration data
 * @param {Object} deviationData - Deviation data from backend
 * @param {Object} origin - Origin coordinates
 * @param {number} forwardHeading - Formation heading in degrees
 * @param {Function} onDroneClick - Callback when drone is clicked
 * @param {Function} onRefresh - Callback to trigger data refresh
 */
const UnifiedPositionPlot = ({
  drones,
  deviationData,
  origin,
  forwardHeading = 0,
  onDroneClick,
  onRefresh
}) => {
  const { isDark } = useTheme();
  const [showDeviations, setShowDeviations] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  // Theme-aware colors
  const themeColors = {
    background: isDark ? '#1a1a1a' : '#f8f9fa',
    paper: isDark ? '#1a1a1a' : '#f8f9fa',
    text: isDark ? '#e9ecef' : '#343a40',
    grid: isDark ? '#495057' : '#dee2e6',
    title: isDark ? '#f8f9fa' : '#212529',
    axisTitle: isDark ? '#adb5bd' : '#6c757d',
  };

  // Auto-refresh mechanism
  useEffect(() => {
    if (!autoRefresh || !onRefresh || !showDeviations) return;

    const interval = setInterval(() => {
      onRefresh();
      setLastUpdate(new Date());
    }, 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, onRefresh, showDeviations]);

  // Extract summary data
  const summary = deviationData?.summary || {
    online: 0,
    within_threshold: 0,
    warnings: 0,
    errors: 0,
    no_telemetry: 0,
    average_deviation: 0
  };

  // Group drones by position (pos_id) for overlap visualization
  const groupedData = {};
  drones.forEach((drone) => {
    if (!groupedData[drone.pos_id]) groupedData[drone.pos_id] = [];
    groupedData[drone.pos_id].push(drone);
  });

  // Build plot traces
  const plotTraces = [];

  // Trace 1: Expected Positions (from trajectory CSV - single source of truth)
  const expectedTrace = {
    x: [],
    y: [],
    text: [],
    customdata: [],
    type: 'scatter',
    mode: 'markers+text',
    name: 'Expected Position',
    marker: {
      size: 14,
      color: '#3b82f6',
      symbol: 'circle',
      line: { color: isDark ? '#60a5fa' : '#2563eb', width: 2 }
    },
    textposition: 'top center',
    textfont: { size: 10, color: themeColors.text },
    hovertemplate: '<b>Position %{customdata.pos_id}</b><br>' +
                   'Expected: (%{x:.2f}m N, %{y:.2f}m E)<br>' +
                   'Assigned to Drone %{customdata.hw_ids}<br>' +
                   '<extra></extra>'
  };

  // Group by pos_id and collect hw_ids for each position
  const positionGroups = {};
  drones.forEach((drone) => {
    const posId = drone.pos_id;
    if (!positionGroups[posId]) {
      positionGroups[posId] = {
        x: parseFloat(drone.x) || 0,
        y: parseFloat(drone.y) || 0,
        hw_ids: []
      };
    }
    positionGroups[posId].hw_ids.push(drone.hw_id);
  });

  // Add expected positions (from trajectory CSV)
  Object.entries(positionGroups).forEach(([posId, data]) => {
    expectedTrace.x.push(data.y); // East (plotly x-axis)
    expectedTrace.y.push(data.x); // North (plotly y-axis)
    expectedTrace.text.push(`P${posId}`);
    expectedTrace.customdata.push({
      pos_id: posId,
      hw_ids: data.hw_ids.join(', ')
    });
  });

  plotTraces.push(expectedTrace);

  // Trace 2 & 3: Actual Positions and Deviations (if enabled)
  if (showDeviations && deviationData) {
    const actualTrace = {
      x: [],
      y: [],
      text: [],
      customdata: [],
      type: 'scatter',
      mode: 'markers+text',
      name: 'Actual Position',
      marker: {
        size: 12,
        color: [],
        symbol: 'circle-open',
        line: { width: 2 }
      },
      textposition: 'bottom center',
      textfont: { size: 9, color: themeColors.text },
      hovertemplate: '<b>Drone %{customdata.hw_id}</b><br>' +
                     'Actual: (%{x:.2f}m N, %{y:.2f}m E)<br>' +
                     'Deviation: %{customdata.total_deviation}m<br>' +
                     'GPS Quality: %{customdata.gps_quality}<br>' +
                     '<extra></extra>'
    };

    const deviationVectors = {
      x: [],
      y: [],
      u: [],
      v: [],
      customdata: [],
      type: 'scatter',
      mode: 'lines',
      line: {
        color: [],
        width: 2
      },
      showlegend: false,
      hoverinfo: 'skip'
    };

    drones.forEach((drone) => {
      const deviation = deviationData[drone.hw_id];
      if (!deviation || !deviation.current_north) return;

      const currentNorth = deviation.current_north;
      const currentEast = deviation.current_east;
      const expectedNorth = parseFloat(drone.x) || 0;
      const expectedEast = parseFloat(drone.y) || 0;

      // Determine status color
      let color = '#22c55e'; // green (ok)
      if (!deviation.within_acceptable_range) {
        if (deviation.total_deviation > 10) {
          color = '#ef4444'; // red (error)
        } else {
          color = '#f59e0b'; // yellow (warning)
        }
      }

      // Actual position
      actualTrace.x.push(currentEast);
      actualTrace.y.push(currentNorth);
      actualTrace.text.push(`D${drone.hw_id}`);
      actualTrace.marker.color.push(color);
      actualTrace.customdata.push({
        hw_id: drone.hw_id,
        total_deviation: deviation.total_deviation?.toFixed(2) || 'N/A',
        gps_quality: deviation.gps_quality || 'Unknown'
      });

      // Deviation vector (from expected to actual)
      deviationVectors.x.push(expectedEast, currentEast, null);
      deviationVectors.y.push(expectedNorth, currentNorth, null);
      deviationVectors.line.color.push(color);
    });

    if (actualTrace.x.length > 0) {
      plotTraces.push(actualTrace);
      plotTraces.push(deviationVectors);
    }
  }

  // Calculate axis ranges with padding
  const allX = plotTraces.flatMap(t => t.x || []).filter(v => v !== null);
  const allY = plotTraces.flatMap(t => t.y || []).filter(v => v !== null);

  const xRange = allX.length > 0 ? [Math.min(...allX) - 5, Math.max(...allX) + 5] : [-10, 10];
  const yRange = allY.length > 0 ? [Math.min(...allY) - 5, Math.max(...allY) + 5] : [-10, 10];

  // Plot layout
  const layout = {
    title: {
      text: showDeviations ? 'Drone Positions & Deviations' : 'Expected Launch Positions',
      font: { color: themeColors.title, size: 18, weight: 600 }
    },
    xaxis: {
      title: { text: 'East (m)', font: { color: themeColors.axisTitle } },
      gridcolor: themeColors.grid,
      zerolinecolor: themeColors.grid,
      color: themeColors.text,
      range: xRange
    },
    yaxis: {
      title: { text: 'North (m)', font: { color: themeColors.axisTitle } },
      gridcolor: themeColors.grid,
      zerolinecolor: themeColors.grid,
      color: themeColors.text,
      range: yRange,
      scaleanchor: 'x',
      scaleratio: 1
    },
    plot_bgcolor: themeColors.background,
    paper_bgcolor: themeColors.paper,
    hovermode: 'closest',
    showlegend: true,
    legend: {
      x: 0.02,
      y: 0.98,
      bgcolor: isDark ? 'rgba(26, 26, 26, 0.8)' : 'rgba(255, 255, 255, 0.8)',
      bordercolor: themeColors.grid,
      borderwidth: 1,
      font: { color: themeColors.text }
    },
    margin: { l: 60, r: 40, t: 60, b: 60 },
    autosize: true
  };

  // Handle drone click
  const handlePlotClick = (data) => {
    if (data.points.length > 0) {
      const point = data.points[0];
      const hwId = point.customdata?.hw_id;
      if (hwId && onDroneClick) {
        onDroneClick(hwId);
      }
    }
  };

  return (
    <div className="unified-position-plot">
      {/* Control Panel */}
      <div className="plot-controls">
        <div className="control-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={showDeviations}
              onChange={(e) => setShowDeviations(e.target.checked)}
            />
            <span>Show Actual Positions & Deviations</span>
          </label>

          {showDeviations && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              <span>Auto-refresh (5s)</span>
            </label>
          )}

          {showDeviations && onRefresh && (
            <button
              className="refresh-button"
              onClick={() => {
                onRefresh();
                setLastUpdate(new Date());
              }}
            >
              🔄 Refresh Now
            </button>
          )}
        </div>

        {showDeviations && (
          <div className="last-update">
            Last update: {lastUpdate.toLocaleTimeString()}
          </div>
        )}
      </div>

      {/* Summary Statistics (only when showing deviations) */}
      {showDeviations && summary.online > 0 && (
        <div className="deviation-summary">
          <div className="summary-item">
            <span className="summary-label">Online:</span>
            <span className="summary-value">{summary.online}</span>
          </div>
          <div className="summary-item">
            <span className="summary-label">Within Threshold:</span>
            <span className="summary-value ok">{summary.within_threshold}</span>
          </div>
          {summary.warnings > 0 && (
            <div className="summary-item">
              <span className="summary-label">Warnings:</span>
              <span className="summary-value warning">{summary.warnings}</span>
            </div>
          )}
          {summary.errors > 0 && (
            <div className="summary-item">
              <span className="summary-label">Errors:</span>
              <span className="summary-value error">{summary.errors}</span>
            </div>
          )}
          <div className="summary-item">
            <span className="summary-label">Avg Deviation:</span>
            <span className="summary-value">{summary.average_deviation?.toFixed(2) || 'N/A'}m</span>
          </div>
        </div>
      )}

      {/* Info Banner */}
      <div className="info-banner">
        <span>📍</span>
        <span>
          Positions from trajectory CSV files (single source of truth)
          {showDeviations && ' • Blue circles = Expected • Colored circles = Actual'}
        </span>
      </div>

      {/* Plot */}
      <div className="plot-container">
        <Plot
          data={plotTraces}
          layout={layout}
          config={{
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
            modeBarButtonsToRemove: ['lasso2d', 'select2d']
          }}
          style={{ width: '100%', height: '600px' }}
          onClick={handlePlotClick}
        />
      </div>
    </div>
  );
};

export default UnifiedPositionPlot;
