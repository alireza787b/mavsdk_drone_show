// src/components/sar/MissionPlanSidebar.js
/**
 * Plan mode sidebar: drone selection, survey config, compute/launch buttons.
 */

import React, { useState } from 'react';
import { FaChevronDown, FaChevronUp } from 'react-icons/fa';
import MissionRecoveryPanel from './MissionRecoveryPanel';
import QuickScoutLaunchReview from './QuickScoutLaunchReview';
import IdentityDoctrineStrip from '../IdentityDoctrineStrip';
import { formatCompactDroneIdentity } from '../../utilities/missionIdentityUtils';
import { QUICKSCOUT_PROFILE_PRESETS } from '../../utilities/quickScoutProfiles';
import {
  calculateCircularAreaSqM,
  calculateCorridorAreaSqM,
  normalizeSearchPath,
} from '../../utilities/quickScoutSearchGeometry';

const isFiniteInputNumber = (value) => (
  value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
);

const parseOptionalNumber = (value) => {
  if (value === '') {
    return '';
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : '';
};

const MissionPlanSidebar = ({
  drones,
  selectedDrones,
  onDroneToggle,
  missionTemplate,
  onMissionTemplateChange,
  searchCenter,
  onSearchCenterChange,
  searchRadiusM,
  onSearchRadiusChange,
  onUseMapCenter,
  searchPath,
  onSearchPathChange,
  corridorWidthM,
  onCorridorWidthChange,
  onAppendMapCenterToPath,
  onUndoSearchPathPoint,
  onClearSearchPath,
  surveyConfig,
  onConfigChange,
  onComputePlan,
  onLaunchMission,
  coveragePlan,
  searchArea,
  computing,
  launching,
  missionProfileId,
  onMissionProfileChange,
  missionLabel,
  onMissionLabelChange,
  missionBrief,
  onMissionBriefChange,
  returnBehavior,
  onReturnBehaviorChange,
  positionSourceMode,
  onPositionSourceModeChange,
  missionCatalog,
  currentMissionId,
  recoveringMissionId,
  loadingMissionCatalog,
  onRecoverMission,
  onStartFreshPlan,
  targetHwIds,
  targetDrones,
  targetSummaryLabel,
  launchReadiness,
  planNeedsRecompute,
  currentMissionState,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showMissionBrief, setShowMissionBrief] = useState(false);
  const isPointMode = missionTemplate === 'last_known_point' || missionTemplate === 'point_dispatch';
  const hasSearchCenter = isFiniteInputNumber(searchCenter?.lat)
    && isFiniteInputNumber(searchCenter?.lng);
  const normalizedSearchPath = normalizeSearchPath(searchPath);

  const hasArea = missionTemplate === 'point_dispatch'
    ? Boolean(hasSearchCenter)
    : missionTemplate === 'last_known_point'
    ? Boolean(hasSearchCenter && Number(searchRadiusM) > 0)
    : missionTemplate === 'corridor_search'
      ? Boolean(normalizedSearchPath.length >= 2 && Number(corridorWidthM) > 0)
      : Boolean(searchArea && searchArea.length >= 3);
  const hasSelection = selectedDrones && selectedDrones.length > 0;
  const canCompute = hasArea && hasSelection && !computing;
  const canLaunch = Boolean(
    coveragePlan
    && !launching
    && !planNeedsRecompute
    && (launchReadiness?.canLaunch ?? true)
  );
  const searchFootprintSqM = missionTemplate === 'last_known_point'
    ? calculateCircularAreaSqM(searchRadiusM)
    : missionTemplate === 'corridor_search'
      ? calculateCorridorAreaSqM(normalizedSearchPath, corridorWidthM)
      : 0;
  const searchFootprintHa = searchFootprintSqM > 0 ? searchFootprintSqM / 10000 : 0;

  const updateConfig = (key, value) => {
    onConfigChange({ ...surveyConfig, [key]: value });
  };

  return (
    <div className="qs-sidebar">
      <div className="qs-sidebar-header">Plan</div>
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

        <div className="qs-config-section">
          <div className="qs-config-title">Mission Type</div>
          <div className="qs-template-grid">
            <button
              type="button"
              className={`qs-template-card ${missionTemplate === 'area_sweep' ? 'active' : ''}`}
              onClick={() => onMissionTemplateChange('area_sweep')}
              title="Polygon search area with multi-drone coverage partitioning."
            >
              <span className="qs-template-label">Area Sweep</span>
            </button>
            <button
              type="button"
              className={`qs-template-card ${missionTemplate === 'point_dispatch' ? 'active' : ''}`}
              onClick={() => onMissionTemplateChange('point_dispatch')}
              title="Fast point dispatch using PX4 mission waypoint behavior."
            >
              <span className="qs-template-label">Point Dispatch</span>
            </button>
            <button
              type="button"
              className={`qs-template-card ${missionTemplate === 'last_known_point' ? 'active' : ''}`}
              onClick={() => onMissionTemplateChange('last_known_point')}
              title="Point-centered search package around a reported location and radius."
            >
              <span className="qs-template-label">Last Known Point</span>
            </button>
            <button
              type="button"
              className={`qs-template-card ${missionTemplate === 'corridor_search' ? 'active' : ''}`}
              onClick={() => onMissionTemplateChange('corridor_search')}
              title="Route-centered search corridor along shoreline, trail, road, or trackline."
            >
              <span className="qs-template-label">Corridor Search</span>
            </button>
          </div>
        </div>

        <div className="qs-config-section">
          <div className="qs-config-title">Mission Setup</div>
          <div className="qs-profile-grid">
            {QUICKSCOUT_PROFILE_PRESETS.map((profile) => (
              <button
                key={profile.id}
                type="button"
                className={`qs-profile-card ${missionProfileId === profile.id ? 'active' : ''}`}
                onClick={() => onMissionProfileChange(profile.id)}
                title={profile.brief}
              >
                <span className="qs-profile-label">{profile.label}</span>
              </button>
            ))}
          </div>
          {missionProfileId === 'custom' && (
            <div className="qs-empty-copy qs-gap-bottom">
              Custom survey settings.
            </div>
          )}

          <div className="qs-config-row qs-config-row-stack">
            <span className="qs-config-label">Mission Label</span>
            <input
              type="text"
              className="qs-config-text-input"
              value={missionLabel}
              onChange={(e) => onMissionLabelChange(e.target.value)}
              placeholder="Optional mission name"
            />
          </div>

          <div
            className="qs-collapsible-header qs-stack-offset"
            onClick={() => setShowMissionBrief(!showMissionBrief)}
          >
            <span className="qs-config-label">Mission Brief</span>
            {showMissionBrief ? <FaChevronUp size={12} /> : <FaChevronDown size={12} />}
          </div>
          {showMissionBrief && (
            <textarea
              className="qs-config-textarea"
              value={missionBrief}
              onChange={(e) => onMissionBriefChange(e.target.value)}
              placeholder="Optional objective, last known report, or search note"
              rows={3}
            />
          )}

          <div className="qs-config-row qs-config-row-stack">
            <span className="qs-config-label">End Behavior</span>
            <div className="qs-choice-row">
              <button
                type="button"
                className={`qs-choice-chip ${returnBehavior === 'return_home' ? 'active' : ''}`}
                onClick={() => onReturnBehaviorChange('return_home')}
              >
                Return Home
              </button>
              <button
                type="button"
                className={`qs-choice-chip ${returnBehavior === 'hold_position' ? 'active' : ''}`}
                onClick={() => onReturnBehaviorChange('hold_position')}
              >
                Hold
              </button>
              <button
                type="button"
                className={`qs-choice-chip ${returnBehavior === 'land_current' ? 'active' : ''}`}
                onClick={() => onReturnBehaviorChange('land_current')}
              >
                Land
              </button>
            </div>
          </div>

          <div className="qs-config-row qs-config-row-stack">
            <span className="qs-config-label">Planning Position</span>
            <div className="qs-choice-row">
              <button
                type="button"
                className={`qs-choice-chip ${positionSourceMode !== 'configured_origin' ? 'active' : ''}`}
                onClick={() => onPositionSourceModeChange?.('live_drone_positions')}
                title="Use fresh drone GPS/global position samples. Required for immediately launchable plans."
              >
                Live GPS
              </button>
              <button
                type="button"
                className={`qs-choice-chip ${positionSourceMode === 'configured_origin' ? 'active' : ''}`}
                onClick={() => onPositionSourceModeChange?.('configured_origin')}
                title="Use configured origin launch slots for offline draft planning. Launch requires live revalidation."
              >
                Origin Slots
              </button>
            </div>
          </div>
        </div>

        {/* Search Area Status */}
        <div className="qs-config-section">
          <div className="qs-config-title">Search Area</div>
          {isPointMode ? (
            <>
              <div className="qs-config-row">
                <span className="qs-config-label">
                  {missionTemplate === 'point_dispatch' ? 'Point' : 'Center'}
                </span>
                <span className="qs-stat-value">
                  {hasSearchCenter
                    ? `${Number(searchCenter.lat).toFixed(4)}, ${Number(searchCenter.lng).toFixed(4)}`
                    : 'Not set'}
                </span>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Latitude</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input qs-config-input-wide"
                    value={searchCenter?.lat ?? ''}
                    onChange={(e) => onSearchCenterChange({
                      lat: parseOptionalNumber(e.target.value),
                      lng: searchCenter?.lng ?? '',
                    })}
                  />
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Longitude</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input qs-config-input-wide"
                    value={searchCenter?.lng ?? ''}
                    onChange={(e) => onSearchCenterChange({
                      lat: searchCenter?.lat ?? '',
                      lng: parseOptionalNumber(e.target.value),
                    })}
                  />
                </div>
              </div>
              {missionTemplate === 'last_known_point' && (
                <>
                  <div className="qs-config-row">
                    <span className="qs-config-label">Radius</span>
                    <div>
                      <input
                        type="number"
                        className="qs-config-input"
                        value={searchRadiusM}
                        onChange={(e) => onSearchRadiusChange(parseFloat(e.target.value) || 0)}
                      />
                      <span className="qs-config-unit">m</span>
                    </div>
                  </div>
                  <div className="qs-config-row">
                    <span className="qs-config-label">Footprint</span>
                    <span className="qs-stat-value">
                      {searchFootprintHa > 0 ? `${searchFootprintHa.toFixed(2)} ha` : 'Not set'}
                    </span>
                  </div>
                </>
              )}
              <button
                type="button"
                className="qs-btn qs-btn-secondary qs-btn-full"
                onClick={onUseMapCenter}
              >
                Use Map Center
              </button>
            </>
          ) : missionTemplate === 'corridor_search' ? (
            <>
              <div className="qs-config-row">
                <span className="qs-config-label">Route points</span>
                <span className="qs-stat-value">{normalizedSearchPath.length}</span>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Width</span>
                <div>
                  <input
                    type="number"
                    className="qs-config-input"
                    value={corridorWidthM}
                    onChange={(e) => onCorridorWidthChange(parseFloat(e.target.value) || 0)}
                  />
                  <span className="qs-config-unit">m</span>
                </div>
              </div>
              <div className="qs-config-row">
                <span className="qs-config-label">Footprint</span>
                <span className="qs-stat-value">
                  {searchFootprintHa > 0 ? `${searchFootprintHa.toFixed(2)} ha` : 'Not set'}
                </span>
              </div>
              <div className="qs-choice-row qs-stack-offset">
                <button
                  type="button"
                  className="qs-choice-chip"
                  onClick={onAppendMapCenterToPath}
                >
                  Add Map Center
                </button>
                <button
                  type="button"
                  className="qs-choice-chip"
                  onClick={onUndoSearchPathPoint}
                  disabled={normalizedSearchPath.length === 0}
                >
                  Undo Last
                </button>
                <button
                  type="button"
                  className="qs-choice-chip"
                  onClick={onClearSearchPath}
                  disabled={normalizedSearchPath.length === 0}
                >
                  Clear Route
                </button>
              </div>
              <div className="qs-search-note qs-stack-offset">
                Add 2+ ordered route points.
              </div>
            </>
          ) : hasArea ? (
            <div className="qs-config-row">
              <span className="qs-config-label">Polygon vertices</span>
              <span className="qs-stat-value">{searchArea.length}</span>
            </div>
          ) : (
            <div className="qs-empty-copy">
              Draw a polygon on the map to define the search area
            </div>
          )}
        </div>

        {/* Drone Selection */}
        <div className="qs-config-section">
          <div className="qs-config-title">Assigned Drones ({selectedDrones.length} selected)</div>
          <div className="qs-drone-list">
            {drones.map((drone) => (
              <label key={drone.hw_ID || drone.hw_id} className="qs-drone-item">
                <input
                  type="checkbox"
                  checked={selectedDrones.includes(drone.pos_id ?? drone.pos_ID)}
                  onChange={() => onDroneToggle(drone.pos_id ?? drone.pos_ID)}
                />
                <span className="qs-drone-id">
                  {formatCompactDroneIdentity(
                    drone.pos_id ?? drone.pos_ID,
                    drone.hw_ID || drone.hw_id,
                    `H${drone.hw_ID || drone.hw_id || '?'}`
                  )}
                </span>
                <span className={`qs-drone-status ${drone.online ? 'online' : 'offline'}`}>
                  {drone.online ? 'Online' : 'Offline'}
                </span>
              </label>
            ))}
            {drones.length === 0 && (
              <div className="qs-empty-copy">
                No drones configured &mdash; add drones in Mission Config
              </div>
            )}
          </div>
          <IdentityDoctrineStrip surface="quickscout" className="qs-identity-doctrine" />
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
            className="qs-collapsible-header qs-stack-offset"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            <span className="qs-config-label">More Options</span>
            {showAdvanced ? <FaChevronUp size={12} /> : <FaChevronDown size={12} />}
          </div>
          {showAdvanced && (
            <div className="qs-stack-tight">
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
                  className="qs-terrain-checkbox"
                  checked={surveyConfig.use_terrain_following}
                  onChange={(e) => updateConfig('use_terrain_following', e.target.checked)}
                />
              </div>
            </div>
          )}
        </div>

        {coveragePlan && (
          <QuickScoutLaunchReview
            coveragePlan={coveragePlan}
            missionLabel={missionLabel}
            missionBrief={missionBrief}
            missionTemplate={missionTemplate}
            missionProfileId={missionProfileId}
            returnBehavior={returnBehavior}
            surveyConfig={surveyConfig}
            searchArea={searchArea}
            searchCenter={searchCenter}
            searchRadiusM={searchRadiusM}
            searchPath={searchPath}
            corridorWidthM={corridorWidthM}
            targetHwIds={targetHwIds}
            targetDrones={targetDrones}
            targetSummaryLabel={targetSummaryLabel}
            launchReadiness={launchReadiness}
            planNeedsRecompute={planNeedsRecompute}
            currentMissionState={currentMissionState}
          />
        )}

        {/* Action Buttons */}
        <div className="qs-sidebar-actions">
          <button
            className="qs-btn qs-btn-primary qs-btn-full"
            onClick={onComputePlan}
            disabled={!canCompute}
          >
            {computing ? 'Planning...' : planNeedsRecompute ? 'Recompute Plan' : 'Compute Plan'}
          </button>

          {coveragePlan && (
            <div className="qs-launch-summary">
              {planNeedsRecompute
                ? 'Mission inputs changed after compute — regenerate the package before launch.'
                : coveragePlan.requires_revalidation
                  ? `${coveragePlan.plans?.length} drones, staged origin plan`
                : `${coveragePlan.plans?.length} drones, ~${(coveragePlan.estimated_coverage_time_s / 60).toFixed(1)} min`}
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
