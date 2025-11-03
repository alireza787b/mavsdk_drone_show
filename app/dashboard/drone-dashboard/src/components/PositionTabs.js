// src/components/PositionTabs.js

import React, { useState } from 'react';
import InitialLaunchPlot from './InitialLaunchPlot';
import DeviationView from './DeviationView';
import '../styles/PositionTabs.css';

/**
 * PositionTabs - Tabbed interface for position visualization
 *
 * Provides two views:
 * 1. Launch Plot - Shows initial/expected launch positions
 * 2. Position Monitoring - Shows expected vs actual positions with deviations
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
  const [activeTab, setActiveTab] = useState('launch');

  const summary = deviationData?.summary || {};
  const hasWarnings = (summary.warnings || 0) > 0;
  const hasErrors = (summary.errors || 0) > 0;

  return (
    <div className="position-tabs-container">
      {/* Tab Navigation */}
      <div className="tab-navigation">
        <button
          className={`tab-button ${activeTab === 'launch' ? 'active' : ''}`}
          onClick={() => setActiveTab('launch')}
        >
          <span className="tab-icon">📍</span>
          Launch Plot
        </button>

        <button
          className={`tab-button ${activeTab === 'deviation' ? 'active' : ''}`}
          onClick={() => setActiveTab('deviation')}
        >
          <span className="tab-icon">📊</span>
          Position Monitoring

          {/* Badge indicators */}
          {(hasWarnings || hasErrors) && (
            <span className="badge-group">
              {hasWarnings && <span className="badge warning">{summary.warnings}</span>}
              {hasErrors && <span className="badge error">{summary.errors}</span>}
            </span>
          )}
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'launch' && (
          <div className="tab-panel fade-in">
            <InitialLaunchPlot
              drones={drones}
              onDroneClick={onDroneClick}
              deviationData={deviationData}
              forwardHeading={forwardHeading}
            />
          </div>
        )}

        {activeTab === 'deviation' && (
          <div className="tab-panel fade-in">
            <DeviationView
              drones={drones}
              deviationData={deviationData}
              origin={origin}
              onDroneClick={onDroneClick}
              onRefresh={onRefresh}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default PositionTabs;
