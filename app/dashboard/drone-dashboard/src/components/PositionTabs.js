// src/components/PositionTabs.js

import React from 'react';
import UnifiedPositionPlot from './UnifiedPositionPlot';
import '../styles/PositionTabs.css';

/**
 * PositionTabs - Unified position visualization
 *
 * Now uses a single unified plot with optional deviation display.
 * Positions are loaded from trajectory CSV files (single source of truth).
 *
 * @param {Array} drones - Drone configuration data
 * @param {Object} deviationData - Deviation data from backend
 * @param {Object} origin - Origin coordinates
 * @param {number} forwardHeading - Formation heading in degrees
 * @param {Function} onDroneClick - Callback when drone is clicked
 * @param {Function} onRefresh - Callback to trigger data refresh
 */
const PositionTabs = ({
  drones,
  deviationData,
  origin,
  forwardHeading,
  onDroneClick,
  onRefresh
}) => {
  return (
    <div className="position-tabs-container">
      <UnifiedPositionPlot
        drones={drones}
        deviationData={deviationData}
        origin={origin}
        forwardHeading={forwardHeading}
        onDroneClick={onDroneClick}
        onRefresh={onRefresh}
      />
    </div>
  );
};

export default PositionTabs;
