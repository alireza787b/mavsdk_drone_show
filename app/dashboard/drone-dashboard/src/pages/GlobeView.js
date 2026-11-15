import React, { useState, useMemo } from 'react';
import { FaExclamationTriangle, FaGlobeAmericas, FaRedoAlt, FaSatelliteDish } from 'react-icons/fa';

import Globe from '../components/Globe';
import GlobeMapView from '../components/GlobeMapView';
import IdentityDoctrineStrip from '../components/IdentityDoctrineStrip';
import ViewModeToggle, { VIEW_MODES } from '../components/map/ViewModeToggle';
import {
  ActionIconButton,
  EmptyState,
  PageShell,
  StatusBadge,
} from '../components/ui';
import '../styles/GlobeView.css';

import useFleetResources from '../features/fleet-overview/useFleetResources';
import { buildGlobeDroneViewModels } from '../utilities/globeTelemetryViewModel';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';

const GlobeView = () => {
  const resources = useFleetResources();
  const [viewMode, setViewMode] = useState(VIEW_MODES.SCENE_3D);
  const [selectedDroneId, setSelectedDroneId] = useState(null);
  const drones = useMemo(() => buildGlobeDroneViewModels(
    Object.fromEntries(resources.drones.map(row => [String(row.hw_id ?? row.hw_ID), row])),
    resources.config.response?.data || [], resources.nowMs,
  ), [resources.drones, resources.config.response, resources.nowMs]);
  const isLoading = resources.loading;
  const error = !resources.telemetry.response && resources.telemetry.error
    ? 'Aircraft updates are unavailable. Reconnecting.' : null;
  const fetchDrones = () => { resources.telemetry.refresh(); resources.config.refresh(); };
  const renderDroneStrip = () => (
    <div className="globe-tactical-strip" aria-label="Live drone selection strip">
      <div className="globe-tactical-strip__drones">
        {drones.map((drone) => {
          const droneId = String(drone.hw_id);
          const selected = String(selectedDroneId || '') === droneId;
          return (
            <button
              key={droneId}
              type="button"
              className={[
                'globe-tactical-strip__chip',
                selected ? 'selected' : '',
                drone.runtime_indicator_class ? `runtime-${drone.runtime_indicator_class}` : '',
              ].filter(Boolean).join(' ')}
              style={{ '--mds-drone-marker-color': drone.marker_color || getPlotThemeColors().primary }}
              onClick={() => setSelectedDroneId(selected ? null : droneId)}
              aria-label={`Select ${formatCompactDroneIdentity(drone.pos_id, drone.hw_id, `H${drone.hw_id}`)} on the active view`}
            >
              {formatCompactDroneIdentity(drone.pos_id, drone.hw_id, `H${drone.hw_id}`)}
            </button>
          );
        })}
      </div>
    </div>
  );

  const renderChrome = (content, { showStrip = drones.length > 0 } = {}) => (
    <PageShell
      className="globe-view-container"
      eyebrow="Live visualization"
      title="Fleet Map"
      icon={<FaGlobeAmericas />}
      docsRoute="/globe-view"
      status={(
        <StatusBadge tone={resources.telemetry.error ? 'warning' : 'info'}>
          {resources.telemetry.error ? 'Updates delayed' : `${drones.length} aircraft`}
        </StatusBadge>
      )}
    >
      <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
      <div className="globe-view-toolbar">
        <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
        {showStrip ? renderDroneStrip() : null}
      </div>
      {content}
    </PageShell>
  );

  if (isLoading) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<span className="globe-view-state__radar"><FaSatelliteDish /></span>}
        title="Loading telemetry"
        detail="Connecting to the fleet stream and mission configuration."
      />,
      { showStrip: false },
    );
  }

  if (error) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<FaExclamationTriangle />}
        title="Telemetry unavailable"
        detail={error}
        action={(
          <ActionIconButton icon={<FaRedoAlt />} label="Retry fleet telemetry load" onClick={fetchDrones}>
            Retry
          </ActionIconButton>
        )}
      />,
      { showStrip: false },
    );
  }

  if (drones.length === 0) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<FaSatelliteDish />}
        title="No telemetry targets"
        detail="No configured or live drones are available for the current runtime."
      />,
      { showStrip: false },
    );
  }

  return renderChrome(
    <>
      {viewMode === VIEW_MODES.SCENE_3D ? (
        <Globe drones={drones} selectedDroneId={selectedDroneId} onSelectDrone={setSelectedDroneId} />
      ) : (
        <GlobeMapView drones={drones} selectedDroneId={selectedDroneId} onSelectDrone={setSelectedDroneId} />
      )}
    </>,
  );
};

export default GlobeView;
