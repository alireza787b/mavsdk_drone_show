// src/components/DeviationView.js

import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { useTheme } from '../hooks/useTheme';
import '../styles/DeviationView.css';

/**
 * DeviationView - Professional position monitoring with expected vs actual positions
 *
 * Features:
 * - Overlaid expected (solid) and current (outlined) positions
 * - Deviation vectors showing displacement
 * - Status-based color coding (ok/warning/error)
 * - GPS quality indicators in tooltips
 * - Auto-refresh every 5 seconds
 * - Summary statistics header
 *
 * @param {Array} drones - Drone configuration data
 * @param {Object} deviationData - Deviation data from /get-position-deviations
 * @param {Object} origin - Origin coordinates
 * @param {Function} onDroneClick - Callback when drone is clicked
 * @param {Function} onRefresh - Callback to trigger manual refresh
 */
const DeviationView = ({
  drones,
  deviationData,
  origin,
  onDroneClick,
  onRefresh
}) => {
  const { isDark } = useTheme();
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  // Theme-aware colors
  const themeColors = {
    background: isDark ? '#1a1a1a' : '#f8f9fa',
    paper: isDark ? '#1a1a1a' : '#f8f9fa',
    text: isDark ? '#e9ecef' : '#343a40',
    grid: isDark ? '#495057' : '#dee2e6',
  };

  // Auto-refresh mechanism - call parent's onRefresh every 5 seconds
  useEffect(() => {
    if (!autoRefresh || !onRefresh) return;

    const interval = setInterval(() => {
      onRefresh();
      setLastUpdate(new Date());
    }, 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, onRefresh]);

  // Extract summary data
  const summary = deviationData?.summary || {
    online: 0,
    within_threshold: 0,
    warnings: 0,
    errors: 0,
    no_telemetry: 0,
    average_deviation: 0,
    best_deviation: 0,
    worst_deviation: 0
  };

  // Build plot traces
  const plotTraces = [];

  // Trace 1: Expected Positions (solid blue circles)
  const expectedTrace = {
    x: [],
    y: [],
    text: [],
    customdata: [],
    type: 'scatter',
    mode: 'markers+text',
    name: 'Expected',
    marker: {
      size: 18,
      color: '#3498db',
      symbol: 'circle',
      line: { width: 2, color: '#2980b9' }
    },
    textfont: {
      color: isDark ? '#ffffff' : '#000000',
      size: 10
    },
    textposition: 'middle center',
    hovertemplate:
      '<b>Expected Position</b><br>' +
      'Drone: %{customdata.hw_id} (P%{customdata.pos_id})<br>' +
      'North: %{customdata.north:.2f}m<br>' +
      'East: %{customdata.east:.2f}m<extra></extra>'
  };

  // Trace 2: Current Positions (outlined, color-coded by status)
  const currentTrace = {
    x: [],
    y: [],
    text: [],
    customdata: [],
    type: 'scatter',
    mode: 'markers',
    name: 'Current',
    marker: {
      size: 24,
      color: [],
      symbol: 'circle-open',
      line: { width: 4 }
    },
    hovertemplate:
      '<b>Current Position</b><br>' +
      'Drone: %{customdata.hw_id} (P%{customdata.pos_id})<br>' +
      'North: %{customdata.current_north:.2f}m<br>' +
      'East: %{customdata.current_east:.2f}m<br>' +
      '<b>Deviation: %{customdata.deviation:.2f}m</b><br>' +
      'GPS: %{customdata.gps_quality} (%{customdata.satellites} sats)<br>' +
      'HDOP: %{customdata.hdop:.1f}<br>' +
      'Status: %{customdata.status}<extra></extra>'
  };

  // Trace 3: Deviation Vectors (lines from expected to current)
  const deviationVectors = {
    x: [],
    y: [],
    mode: 'lines',
    type: 'scatter',
    name: 'Deviation',
    line: { width: 2, color: 'rgba(231, 76, 60, 0.5)' },
    hoverinfo: 'skip',
    showlegend: false
  };

  // Status color mapping
  const statusColors = {
    'ok': '#27ae60',
    'warning': '#f39c12',
    'error': '#e74c3c',
    'no_telemetry': '#95a5a6'
  };

  // Build traces from deviation data
  if (deviationData?.deviations) {
    drones.forEach(drone => {
      const hw_id = drone.hw_id;
      const deviation = deviationData.deviations[hw_id];

      if (!deviation || !deviation.expected) return;

      // Expected position (always show)
      const expectedNorth = deviation.expected.north || 0;
      const expectedEast = deviation.expected.east || 0;

      expectedTrace.x.push(expectedEast);
      expectedTrace.y.push(expectedNorth);
      expectedTrace.text.push(hw_id);
      expectedTrace.customdata.push({
        hw_id,
        pos_id: drone.pos_id || hw_id,
        north: expectedNorth,
        east: expectedEast
      });

      // Current position (if available)
      if (deviation.current && deviation.status !== 'no_telemetry') {
        const currentNorth = deviation.current.north;
        const currentEast = deviation.current.east;

        currentTrace.x.push(currentEast);
        currentTrace.y.push(currentNorth);
        currentTrace.text.push('');

        // Status-based color
        currentTrace.marker.color.push(
          statusColors[deviation.status] || statusColors.no_telemetry
        );

        currentTrace.customdata.push({
          hw_id,
          pos_id: drone.pos_id || hw_id,
          current_north: currentNorth,
          current_east: currentEast,
          deviation: deviation.deviation?.horizontal || 0,
          gps_quality: deviation.current.gps_quality || 'unknown',
          satellites: deviation.current.satellites || 0,
          hdop: deviation.current.hdop || 99,
          status: deviation.status
        });

        // Deviation vector (arrow from expected to current)
        deviationVectors.x.push(expectedEast, currentEast, null);
        deviationVectors.y.push(expectedNorth, currentNorth, null);
      }
    });
  }

  plotTraces.push(expectedTrace, currentTrace, deviationVectors);

  return (
    <div className="deviation-view">
      {/* Auto-refresh toggle and manual refresh button */}
      <div className="deviation-controls">
        <label className="auto-refresh-toggle">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          <span>Auto-refresh (5s)</span>
          {autoRefresh && <span className="refresh-indicator">●</span>}
        </label>

        <button
          className="manual-refresh-btn"
          onClick={() => {
            if (onRefresh) {
              onRefresh();
              setLastUpdate(new Date());
            }
          }}
          disabled={!onRefresh}
        >
          🔄 Refresh Now
        </button>
      </div>

      {/* Summary Statistics Header */}
      <div className="deviation-summary">
        <div className="stat-card">
          <span className="stat-value">{summary.online}</span>
          <span className="stat-label">Online</span>
        </div>
        <div className="stat-card success">
          <span className="stat-value">{summary.within_threshold}</span>
          <span className="stat-label">OK</span>
        </div>
        <div className="stat-card warning">
          <span className="stat-value">{summary.warnings}</span>
          <span className="stat-label">Warnings</span>
        </div>
        <div className="stat-card error">
          <span className="stat-value">{summary.errors}</span>
          <span className="stat-label">Errors</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">
            {summary.average_deviation ? summary.average_deviation.toFixed(2) : '0.00'}m
          </span>
          <span className="stat-label">Avg Deviation</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">
            {summary.worst_deviation ? summary.worst_deviation.toFixed(2) : '0.00'}m
          </span>
          <span className="stat-label">Worst</span>
        </div>
      </div>

      {/* Main Plot */}
      <div className="deviation-plot-container">
        {origin?.lat && origin?.lon ? (
          <Plot
            data={plotTraces}
            layout={{
              title: {
                text: 'Position Monitoring - Expected vs Current',
                font: { color: themeColors.text, size: 16 }
              },
              xaxis: {
                title: '← West | East →',
                showgrid: true,
                zeroline: true,
                gridcolor: themeColors.grid,
                tickfont: { color: themeColors.text }
              },
              yaxis: {
                title: '← South | North →',
                showgrid: true,
                zeroline: true,
                gridcolor: themeColors.grid,
                tickfont: { color: themeColors.text }
              },
              hovermode: 'closest',
              showlegend: true,
              legend: {
                x: 1.02,
                y: 1,
                font: { color: themeColors.text }
              },
              plot_bgcolor: themeColors.background,
              paper_bgcolor: themeColors.paper,
              margin: { l: 60, r: 120, t: 60, b: 60 }
            }}
            style={{ width: '100%', height: '600px' }}
            config={{ responsive: true }}
            onClick={(data) => {
              const hw_id = data.points[0]?.customdata?.hw_id;
              if (hw_id && onDroneClick) {
                onDroneClick(hw_id);
              }
            }}
          />
        ) : (
          <div className="no-origin-message">
            <p>Please set origin coordinates to view position monitoring.</p>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="deviation-legend">
        <div className="legend-item">
          <span className="marker expected"></span>
          <span>Expected Position</span>
        </div>
        <div className="legend-item">
          <span className="marker current ok"></span>
          <span>Current (OK &lt; 2m)</span>
        </div>
        <div className="legend-item">
          <span className="marker current warning"></span>
          <span>Current (Warning 2-5m)</span>
        </div>
        <div className="legend-item">
          <span className="marker current error"></span>
          <span>Current (Error &gt; 5m)</span>
        </div>
        <div className="legend-item">
          <span className="line deviation"></span>
          <span>Deviation Vector</span>
        </div>
      </div>

      {/* Last Updated */}
      <div className="last-updated">
        Last updated: {lastUpdate.toLocaleTimeString()}
      </div>
    </div>
  );
};

export default DeviationView;
