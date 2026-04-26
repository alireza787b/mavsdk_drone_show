// src/components/DeviationView.js

import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { formatCompactDroneIdentity, normalizeComparableId } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';
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
 * @param {Object} deviationData - Deviation data from /api/v1/origin/deviations
 * @param {Object} origin - Origin coordinates
 * @param {Function} onDroneClick - Callback when drone is clicked
 * @param {Function} onRefresh - Callback to trigger manual refresh
 */
const DeviationView = ({
  drones,
  deviationData,
  trajectoryPositionsByPosId,
  origin,
  onDroneClick,
  onRefresh
}) => {
  const [showActualPositions, setShowActualPositions] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  const themeColors = getPlotThemeColors();

  // Auto-refresh mechanism - call parent's onRefresh every 5 seconds (only if showing actual positions)
  useEffect(() => {
    if (!autoRefresh || !onRefresh || !showActualPositions) return;

    const interval = setInterval(() => {
      onRefresh();
      setLastUpdate(new Date());
    }, 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, onRefresh, showActualPositions]);

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
      color: themeColors.primary,
      symbol: 'circle',
      line: { width: 2, color: themeColors.primaryHover }
    },
    textfont: {
      color: themeColors.text,
      size: 10
    },
    textposition: 'middle center',
    hovertemplate:
      '<b>Expected Position</b><br>' +
      '%{customdata.identity}<br>' +
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
      line: { width: 4, color: [] }
    },
    hovertemplate:
      '<b>Current Position</b><br>' +
      '%{customdata.identity}<br>' +
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
    line: { width: 2, color: themeColors.danger },
    hoverinfo: 'skip',
    showlegend: false
  };

  // Status color mapping
  const statusColors = {
    'ok': themeColors.success,
    'warning': themeColors.warning,
    'error': themeColors.danger,
    'no_telemetry': themeColors.muted
  };

  // Thresholds for deviation-based coloring (matches backend logic)
  // Border color should reflect actual deviation, not GPS quality warnings
  const thresholdWarning = 3.0;  // acceptable_deviation from Params
  const thresholdError = 7.5;    // threshold_warning * 2.5

  // Get border color based on actual deviation value
  const getBorderColorByDeviation = (deviationValue) => {
    // Handle missing or invalid deviation values
    if (deviationValue === undefined || deviationValue === null || isNaN(deviationValue)) {
      return statusColors.no_telemetry;
    }
    
    // Convert to number if it's a string
    const dev = typeof deviationValue === 'string' ? parseFloat(deviationValue) : deviationValue;
    
    // Border color reflects actual position accuracy
    if (dev <= thresholdWarning) {
      return statusColors.ok;      // Green: deviation is acceptable (≤ 3.0m)
    } else if (dev <= thresholdError) {
      return statusColors.warning; // Yellow: deviation exceeds warning threshold (3.0m < x ≤ 7.5m)
    } else {
      return statusColors.error;   // Red: deviation exceeds error threshold (> 7.5m)
    }
  };

  const deviationLookup = deviationData?.deviations || {};

  drones.forEach((drone) => {
    const hwId = normalizeComparableId(drone.hw_id);
    const posId = normalizeComparableId(drone.pos_id, hwId) || hwId;
    const deviation = deviationLookup[hwId];
    const trajectoryPosition = trajectoryPositionsByPosId?.[posId];

    let expectedNorth = Number(trajectoryPosition?.x);
    let expectedEast = Number(trajectoryPosition?.y);

    if (!Number.isFinite(expectedNorth) || !Number.isFinite(expectedEast)) {
      expectedNorth = Number(deviation?.expected?.north);
      expectedEast = Number(deviation?.expected?.east);
    }

    if (!Number.isFinite(expectedNorth) || !Number.isFinite(expectedEast)) {
      return;
    }

    expectedTrace.x.push(expectedEast);
    expectedTrace.y.push(expectedNorth);
    expectedTrace.text.push(hwId);
    expectedTrace.customdata.push({
      hw_id: hwId,
      pos_id: posId,
      identity: formatCompactDroneIdentity(posId, hwId, `H${hwId}`),
      north: expectedNorth,
      east: expectedEast,
    });

    if (!deviation?.current || deviation.status === 'no_telemetry') {
      return;
    }

    const currentNorth = Number(deviation.current.north);
    const currentEast = Number(deviation.current.east);
    if (!Number.isFinite(currentNorth) || !Number.isFinite(currentEast)) {
      return;
    }

    currentTrace.x.push(currentEast);
    currentTrace.y.push(currentNorth);
    currentTrace.text.push('');

    const deviationValue = deviation.deviation?.horizontal;
    const borderColor = getBorderColorByDeviation(deviationValue);
    currentTrace.marker.color.push(borderColor);
    currentTrace.marker.line.color.push(borderColor);

    currentTrace.customdata.push({
      hw_id: hwId,
      pos_id: posId,
      identity: formatCompactDroneIdentity(posId, hwId, `H${hwId}`),
      current_north: currentNorth,
      current_east: currentEast,
      deviation: deviation.deviation?.horizontal || 0,
      gps_quality: deviation.current.gps_quality || 'unknown',
      satellites: deviation.current.satellites || 0,
      hdop: deviation.current.hdop || 99,
      status: deviation.status,
    });

    deviationVectors.x.push(expectedEast, currentEast, null);
    deviationVectors.y.push(expectedNorth, currentNorth, null);
  });

  const hasExpectedPositions = expectedTrace.x.length > 0;

  // Only add actual positions and deviations if enabled
  plotTraces.push(expectedTrace);
  if (showActualPositions) {
    plotTraces.push(currentTrace, deviationVectors);
  }

  return (
    <div className="deviation-view">
      {/* Controls */}
      <div className="deviation-controls">
        <label className="auto-refresh-toggle">
          <input
            type="checkbox"
            checked={showActualPositions}
            onChange={(e) => setShowActualPositions(e.target.checked)}
          />
          <span>Show Actual Positions & Deviations</span>
        </label>

        {showActualPositions && (
          <>
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
          </>
        )}
      </div>

      {/* Info Banner */}
      <div className="info-banner">
        📍 Positions from trajectory CSV files (single source of truth)
      </div>

      {/* Summary Statistics Header (only when showing actual positions) */}
      {showActualPositions && (
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
      )}

      {/* Main Plot */}
      <div className="deviation-plot-container">
        {origin?.lat && origin?.lon ? (
          hasExpectedPositions ? (
            <Plot
              data={plotTraces}
              layout={{
                title: {
                  text: showActualPositions ? 'Position Monitoring - Expected vs Current' : 'Expected Launch Positions',
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
              <p>Trajectory-based launch positions are not available yet.</p>
            </div>
          )
        ) : (
          <div className="no-origin-message">
            <p>Please set origin coordinates to view position monitoring.</p>
          </div>
        )}
      </div>

      {/* Legend (only when showing actual positions) */}
      {showActualPositions && (
        <>
          <div className="deviation-legend">
            <div className="legend-item">
              <span className="marker expected"></span>
              <span>Expected Position</span>
            </div>
            <div className="legend-item">
              <span className="marker current ok"></span>
              <span>Current (OK ≤ 3m)</span>
            </div>
            <div className="legend-item">
              <span className="marker current warning"></span>
              <span>Current (Warning 3–7.5m)</span>
            </div>
            <div className="legend-item">
              <span className="marker current error"></span>
              <span>Current (Error &gt; 7.5m)</span>
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
        </>
      )}
    </div>
  );
};

export default DeviationView;
