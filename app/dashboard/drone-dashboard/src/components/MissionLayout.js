// src/components/MissionLayout.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import '../styles/MissionLayout.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faMapMarkerAlt, faDownload, faPrint } from '@fortawesome/free-solid-svg-icons';
import { generateKML } from '../utilities/missionConfigUtilities';
import OriginModal from './OriginModal';

/**
 * MissionLayout
 *
 * Unified mission action bar with expert UI/UX layout:
 * - Export actions (left) grouped logically
 * - Origin controls and status (right) for balance
 */
const MissionLayout = ({ configData, origin, openOriginModal }) => {
  const [showOriginModal, setShowOriginModal] = useState(false);

  // Handle printing the mission briefing
  const handlePrint = () => {
    window.print();
  };

  // Export the drone positions to a KML file for Google Earth
  const exportToKML = () => {
    if (!origin.lat || !origin.lon) {
      setShowOriginModal(true);
      return;
    }

    if (isNaN(origin.lat) || isNaN(origin.lon)) {
      alert('Origin latitude and longitude must be valid numbers.');
      return;
    }

    const kmlContent = generateKML(configData, origin.lat, origin.lon);
    const blob = new Blob([kmlContent], { type: 'application/vnd.google-earth.kml+xml' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = 'drone_positions.kml';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOriginSubmit = (newOrigin) => {
    // Use the existing openOriginModal functionality instead
    setShowOriginModal(false);
    exportToKML();
  };

  return (
    <div className="mission-layout">
      {/* Expert UI/UX Layout: Single-line with logical grouping */}
      <div className="mission-action-bar">
        {/* Export Actions Group (Left) */}
        <div className="export-actions-group">
          <button className="export-kml-btn" onClick={exportToKML} title="Export drone positions to KML">
            <FontAwesomeIcon icon={faDownload} />
            Export to Google Earth (KML)
          </button>
          <button className="print-mission-btn" onClick={handlePrint} title="Print the mission briefing">
            <FontAwesomeIcon icon={faPrint} />
            Print Mission Briefing
          </button>
        </div>

        {/* Origin Controls Group (Right) */}
        <div className="origin-controls-group">
          <button className="set-origin-btn" onClick={openOriginModal}>
            <FontAwesomeIcon icon={faMapMarkerAlt} />
            Set Origin
          </button>
          {origin.lat !== null && origin.lon !== null && (
            <div className="current-origin">
              <p>
                <strong>Origin:</strong>
              </p>
              <p className="coordinates">
                <span className="coord-label">Lat:</span> <span className="coord-value">{Number(origin.lat).toFixed(6)}</span>
                <br />
                <span className="coord-label">Lon:</span> <span className="coord-value">{Number(origin.lon).toFixed(6)}</span>
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Origin Modal for KML export when no origin is set */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={{}}
          configData={configData}
          currentOrigin={origin}
        />
      )}
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
