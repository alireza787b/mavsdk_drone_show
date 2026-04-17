// src/components/GlobeControlBox.js
import React from 'react';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import '../styles/GlobeControlBox.css';

function buildDroneClusterGroups(drones = []) {
  const droneMap = new Map(
    drones
      .filter((drone) => drone?.[FIELD_NAMES.HW_ID] !== undefined && drone?.[FIELD_NAMES.HW_ID] !== null)
      .map((drone) => [String(drone[FIELD_NAMES.HW_ID]), drone]),
  );

  const resolveRootId = (droneId, seen = new Set()) => {
    const normalizedId = String(droneId || '');
    const drone = droneMap.get(normalizedId);
    if (!drone) {
      return normalizedId;
    }

    const followId = String(drone.follow_mode ?? '0');
    if (!followId || followId === '0' || followId === normalizedId || seen.has(normalizedId)) {
      return normalizedId;
    }

    seen.add(normalizedId);
    return resolveRootId(followId, seen);
  };

  const groups = new Map();
  drones.forEach((drone) => {
    const droneId = String(drone?.[FIELD_NAMES.HW_ID] ?? '');
    if (!droneId) {
      return;
    }

    const rootId = resolveRootId(droneId);
    const rootDrone = droneMap.get(rootId) || drone;
    const rootLabel = formatCompactDroneIdentity(
      rootDrone?.[FIELD_NAMES.POS_ID],
      rootId,
      `H${rootId}`,
    );
    const group = groups.get(rootId) || {
      id: rootId,
      label: `${rootLabel} cluster`,
      drones: [],
    };

    group.drones.push({
      id: droneId,
      label: formatCompactDroneIdentity(
        drone?.[FIELD_NAMES.POS_ID],
        droneId,
        `H${droneId}`,
      ),
      leader: droneId === rootId,
    });
    groups.set(rootId, group);
  });

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      drones: group.drones.sort((left, right) => {
        if (left.leader !== right.leader) {
          return left.leader ? -1 : 1;
        }
        return left.label.localeCompare(right.label, undefined, { numeric: true });
      }),
    }))
    .sort((left, right) => left.label.localeCompare(right.label, undefined, { numeric: true }));
}

function GlobeControlBox({ 
  drones = [],
  setShowGround, 
  showGround, 
  setGroundLevel, 
  groundLevel, 
  toggleDroneVisibility, 
  droneVisibility, 
  isToolboxOpen,
  showGrid, 
  setShowGrid, 
  handleGetTerrainClick 
}) {
  const groupedDrones = React.useMemo(() => buildDroneClusterGroups(drones), [drones]);

  return (
    <div className={`globe-control-box ${isToolboxOpen ? 'show' : 'hide'}`}>
      <div className="globe-control-box__header">
        <div>
          <p className="globe-control-box__eyebrow">3D view</p>
          <h4>View Filters</h4>
        </div>
      </div>
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGround}
            onChange={(e) => setShowGround(e.target.checked)}
          />
          Ground
        </label>
      </div>
      <div className="control-section">
        <label className="control-label">
          Ground level
          <input 
            type="number" 
            min={-2000} 
            max={15000} 
            step="1" 
            value={groundLevel} 
            onChange={(e) => setGroundLevel(Number(e.target.value))}
            className="number-input"
          />
        </label>
        <button 
          onClick={handleGetTerrainClick} 
          className="get-terrain-button"
        >
          Load Terrain
        </button>
      </div>
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGrid}
            onChange={() => setShowGrid(!showGrid)}
          />
          Grid
        </label>
      </div>
      <div className="control-section drone-toggles">
        <h5>Visible Drones</h5>
        {groupedDrones.map((group) => (
          <div key={group.id} className="drone-toggle-group">
            {groupedDrones.length > 1 && (
              <div className="drone-toggle-group__title">{group.label}</div>
            )}
            {group.drones.map((drone) => (
              <div key={drone.id} className="drone-toggle">
                <label>
                  <input
                    type="checkbox"
                    checked={Boolean(droneVisibility[drone.id])}
                    onChange={() => toggleDroneVisibility(drone.id)}
                  />
                  <span>{drone.label}</span>
                </label>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default GlobeControlBox;
