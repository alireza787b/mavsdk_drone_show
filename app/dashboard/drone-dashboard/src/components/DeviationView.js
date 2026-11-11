// src/components/DeviationView.js

import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { MdRefresh } from 'react-icons/md';
import { formatCompactDroneIdentity, normalizeComparableId } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';
import '../styles/LaunchGeometryView.css';

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

  const themeColors = getPlotThemeColors();

  // Auto-refresh mechanism - call parent's onRefresh every 5 seconds (only if showing actual positions)
  useEffect(() => {
    if (!autoRefresh || !onRefresh || !showActualPositions) return;

    const interval = setInterval(() => {
      onRefresh();
    }, 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, onRefresh, showActualPositions]);

  // Extract summary data
  const summary = deviationData?.summary || {};
  const metric = value => typeof value === 'number' && Number.isFinite(value) ? value : '—';
  const hasOrigin = [origin?.lat, origin?.lon].every(value => typeof value === 'number' && Number.isFinite(value));

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
          <span>Current positions</span>
        </label>

        {showActualPositions && (
          <>
            <label className="auto-refresh-toggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              <span title="Refresh position evidence every five seconds">Auto</span>
            </label>

            <button
              className="manual-refresh-btn"
              onClick={() => {
                if (onRefresh) {
                  onRefresh();
                }
              }}
              disabled={!onRefresh}
            >
              <MdRefresh aria-hidden="true" />
              <span>Refresh</span>
            </button>
          </>
        )}
      </div>

      {/* Summary Statistics Header (only when showing actual positions) */}
      {showActualPositions && (
        <div className="deviation-summary">
        <div className="stat-card">
          <span className="stat-value">{metric(summary.within_threshold)}/{metric(summary.online)}</span>
          <span className="stat-label">Within range</span>
        </div>
        <div className={`stat-card${summary.errors > 0 ? ' error' : summary.warnings > 0 ? ' warning' : ''}`}>
          <span className="stat-value">{typeof summary.errors === 'number' && typeof summary.warnings === 'number' ? summary.errors + summary.warnings : '—'}</span>
          <span className="stat-label">Review</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">
            {typeof summary.worst_deviation === 'number' && Number.isFinite(summary.worst_deviation) ? `${summary.worst_deviation.toFixed(1)} m` : '—'}
          </span>
          <span className="stat-label">Worst</span>
        </div>
      </div>
      )}

      {/* Main Plot */}
      <div className="deviation-plot-container">
        {hasOrigin ? (
          hasExpectedPositions ? (
            <Plot
              data={plotTraces}
              layout={{
                title: {
                  text: showActualPositions ? 'Expected / Current' : 'Expected launch positions',
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
                  orientation: 'h',
                  x: 0,
                  y: 1.12,
                  font: { color: themeColors.text }
                },
                plot_bgcolor: themeColors.background,
                paper_bgcolor: themeColors.paper,
                margin: { l: 50, r: 20, t: 80, b: 50 }
              }}
              style={{ width: '100%', height: 'clamp(320px, 42vh, 480px)' }}
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
          <details className="deviation-key"><summary>Plot key</summary><div className="deviation-legend">
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
          </div></details>
        </>
      )}
    </div>
  );
};

export default DeviationView;
