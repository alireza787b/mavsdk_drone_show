// src/components/sar/MissionPlanSidebar.js
/**
 * Plan mode sidebar: drone selection, survey config, compute/launch buttons.
 */

import React, { useState } from 'react';
import { FaChevronDown, FaChevronUp } from 'react-icons/fa';
import MissionRecoveryPanel from './MissionRecoveryPanel';

const MissionPlanSidebar = ({
  drones,
  selectedDrones,
  onDroneToggle,
  surveyConfig,
  onConfigChange,
  onComputePlan,
  onLaunchMission,
  coveragePlan,
  searchArea,
  computing,
  launching,
  missionCatalog,
  currentMissionId,
  recoveringMissionId,
  loadingMissionCatalog,
  onRecoverMission,
  onStartFreshPlan,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const hasArea = searchArea && searchArea.length >= 3;
  const hasSelection = selectedDrones && selectedDrones.length > 0;
  const canCompute = hasArea && hasSelection && !computing;
  const canLaunch = coveragePlan && !launching;

  const updateConfig = (key, value) => {
    onConfigChange({ ...surveyConfig, [key]: value });
  };

  return (
    <div className="qs-sidebar">
      <div className="qs-sidebar-header">Mission Planning</div>
      <div className="qs-sidebar-content">
        <MissionRecoveryPanel
          missions={missionCatalog}
          currentMissionId={currentMissionId}
          recoveringMissionId={recoveringMissionId}
          loading={loadingMissionCatalog}
          onRecoverMission={onRecoverMission}
          onStartFreshPlan={onStartFreshPlan}
          showStartFresh={Boolean(currentMissionId)}
        />

        {/* Search Area Status */}
        <div className="qs-config-section">
          <div className="qs-config-title">Search Area</div>
          {hasArea ? (
            <div className="qs-config-row">
              <span className="qs-config-label">Polygon vertices</span>
              <span className="qs-stat-value">{searchArea.length}</span>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
              Draw a polygon on the map to define the search area
            </div>
          )}
        </div>

        {/* Drone Selection */}
        <div className="qs-config-section">
          <div className="qs-config-title">Drones ({selectedDrones.length} selected)</div>
          <div className="qs-drone-list">
            {drones.map((drone) => (
              <label key={drone.hw_ID || drone.hw_id} className="qs-drone-item">
                <input
                  type="checkbox"
                  checked={selectedDrones.includes(drone.pos_id ?? drone.pos_ID)}
                  onChange={() => onDroneToggle(drone.pos_id ?? drone.pos_ID)}
                />
                <span className="qs-drone-id">#{drone.hw_ID || drone.hw_id}</span>
                <span className={`qs-drone-status ${drone.online ? 'online' : 'offline'}`}>
                  {drone.online ? 'Online' : 'Offline'}
                </span>
              </label>
            ))}
            {drones.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                No drones configured &mdash; add drones in Mission Config
              </div>
            )}
          </div>
        </div>

        {/* Quick Config */}
        <div className="qs-config-section">
          <div className="qs-config-title">Survey Parameters</div>
          <div className="qs-config-row">
            <span className="qs-config-label">Survey Alt (AGL)</span>
            <div>
              <input
                type="number"
                className="qs-config-input"
                value={surveyConfig.survey_altitude_agl}
                onChange={(e) => updateConfig('survey_altitude_agl', parseFloat(e.target.value) || 40)}
              />
              <span className="qs-config-unit">m</span>
            </div>
          </div>
          <div className="qs-config-row">
            <span className="qs-config-label">Cruise Alt (MSL)</span>
            <div>
              <input
                type="number"
                className="qs-config-input"
                value={surveyConfig.cruise_altitude_msl}
                onChange={(e) => updateConfig('cruise_altitude_msl', parseFloat(e.target.value) || 50)}
              />
              <span className="qs-config-unit">m</span>
            </div>
          </div>
          <div className="qs-config-row">
            <span className="qs-config-label">Sweep Width</span>
            <div>
              <input
                type="number"
                className="qs-config-input"
                value={surveyConfig.sweep_width_m}
                onChange={(e) => updateConfig('sweep_width_m', parseFloat(e.target.value) || 30)}
              />
              <span className="qs-config-unit">m</span>
            </div>
          </div>

          {/* Advanced Options */}
          <div
            className="qs-collapsible-header"
            onClick={() => setShowAdvanced(!showAdvanced)}
            style={{ marginTop: 8 }}
          >
            <span className="qs-config-label">More Options</span>
            {showAdvanced ? <FaChevronUp size={12} /> : <FaChevronDown size={12} />}
          </div>
          {showAdvanced && (
            <div style={{ marginTop: 6 }}>
              <div className="qs-config-row">
                <span className="qs-config-label">Overlap</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input"
                    value={surveyConfig.overlap_percent}
                    onChange={(e) => updateConfig('overlap_percent', parseFloat(e.target.value) || 10)}
                  />
                  <span className="qs-config-unit">%</span>
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Survey Speed</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input"
                    value={surveyConfig.survey_speed_ms}
                    onChange={(e) => updateConfig('survey_speed_ms', parseFloat(e.target.value) || 5)}
                  />
                  <span className="qs-config-unit">m/s</span>
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Cruise Speed</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input"
                    value={surveyConfig.cruise_speed_ms}
                    onChange={(e) => updateConfig('cruise_speed_ms', parseFloat(e.target.value) || 10)}
                  />
                  <span className="qs-config-unit">m/s</span>
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Camera Interval</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input"
                    value={surveyConfig.camera_interval_s}
                    onChange={(e) => updateConfig('camera_interval_s', parseFloat(e.target.value) || 2)}
                  />
                  <span className="qs-config-unit">s</span>
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Terrain Following</span>
                <input
                  type="checkbox"
                  checked={surveyConfig.use_terrain_following}
                  onChange={(e) => updateConfig('use_terrain_following', e.target.checked)}
                  style={{ accentColor: 'var(--color-primary)' }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button
            className="qs-btn qs-btn-primary qs-btn-full"
            onClick={onComputePlan}
            disabled={!canCompute}
          >
            {computing ? 'Computing...' : 'Compute Plan'}
          </button>

          {coveragePlan && (
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', textAlign: 'center' }}>
              {coveragePlan.plans?.length} drones, ~{(coveragePlan.estimated_coverage_time_s / 60).toFixed(1)} min
            </div>
          )}

          <button
            className="qs-btn qs-btn-success qs-btn-full"
            onClick={onLaunchMission}
            disabled={!canLaunch}
          >
            {launching ? 'Launching...' : 'START MISSION'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MissionPlanSidebar;
