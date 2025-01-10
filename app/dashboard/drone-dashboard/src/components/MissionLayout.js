// app/dashboard/drone-dashboard/src/components/MissionLayout.js
import React from 'react';
import PropTypes from 'prop-types';
import '../styles/MissionLayout.css';
import BriefingExport from './BriefingExport';

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

      {/* KML Output */}
      <div className="kml-output-section">
        <h4>KML Output</h4>
        <button className="export-kml-btn">
          Download KML
        </button>
      </div>

      {/* Set Origin */}
      <div className="set-origin-section">
        <button className="set-origin-btn" onClick={openOriginModal}>
          <i className="fa fa-map-marker-alt"></i> Set Origin
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
