// app/dashboard/drone-dashboard/src/pages/GlobeView.js
import React from 'react';
import Globe from '../components/Globe';
import PropTypes from 'prop-types';
import '../styles/GlobeView.css';

const GlobeView = ({ drones }) => {
  return (
    <div className="globe-view-container">
      <h2>Drone 3D Map View</h2>
      <Globe 
        drones={drones.map(drone => ({
          hw_ID: drone.hw_ID,
          position: [drone.Position_Lat, drone.Position_Long, drone.Position_Alt],
          state: drone.State,
          follow_mode: drone.Follow_Mode,
          altitude: drone.Position_Alt
        }))}
      />
    </div>
  );
};

GlobeView.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_ID: PropTypes.string.isRequired,
    Position_Lat: PropTypes.number.isRequired,
    Position_Long: PropTypes.number.isRequired,
    Position_Alt: PropTypes.number.isRequired,
    State: PropTypes.string.isRequired,
    Follow_Mode: PropTypes.number.isRequired,
  })).isRequired,
};

export default GlobeView;
