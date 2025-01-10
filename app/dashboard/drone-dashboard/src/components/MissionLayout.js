// app/dashboard/drone-dashboard/src/components/MissionLayout.js
import React from 'react';
import PropTypes from 'prop-types';
import '../styles/MissionLayout.css';
import BriefingExport from './BriefingExport';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
    faMapMarkerAlt,
  } from '@fortawesome/free-solid-svg-icons';
const MissionLayout = ({ configData, origin, openOriginModal }) => {
  return (
    <div className="mission-layout">
      {/* Briefing Export */}
      <BriefingExport
        configData={configData}
        originLat={origin.lat}
        originLon={origin.lon}
        setOriginLat={() => {}} // Not required here
        setOriginLon={() => {}} // Not required here
      />

      {/* Set Origin */}
      <div className="set-origin-section">
        <button className="set-origin-btn" onClick={openOriginModal}>
        <FontAwesomeIcon icon={faMapMarkerAlt} />
        Set Origin
        </button>
        {origin.lat && origin.lon && (
          <div className="current-origin">
            <p>
              <strong>Origin:</strong> Lat: {origin.lat}, Lon: {origin.lon}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

MissionLayout.propTypes = {
  configData: PropTypes.array.isRequired,
  origin: PropTypes.shape({
    lat: PropTypes.number,
    lon: PropTypes.number,
  }).isRequired,
  openOriginModal: PropTypes.func.isRequired,
};

export default MissionLayout;
