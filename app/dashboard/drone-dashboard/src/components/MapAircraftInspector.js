import React from 'react';
import PropTypes from 'prop-types';
import TacticalDroneCard from './TacticalDroneCard';
import '../styles/MapAircraftInspector.css';

// A provider-independent viewport owner. Aircraft content can grow without
// clipping behind a map edge or needing a second projected-height estimate.
export default function MapAircraftInspector({ drone, onClose, noMapFix = false }) {
  return <aside className="fleet-map-inspector" aria-label="Aircraft inspector"
    onPointerDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}>
    {noMapFix && <div className="fleet-map-inspector__note">No current map position</div>}
    <TacticalDroneCard drone={drone} onClose={onClose} />
  </aside>;
}
MapAircraftInspector.propTypes = { drone: PropTypes.object.isRequired, onClose: PropTypes.func.isRequired, noMapFix: PropTypes.bool };
