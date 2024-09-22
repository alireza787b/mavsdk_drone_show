// app/dashboard/drone-dashboard/src/components/BriefingExport.js

import React, { useState } from 'react';
import { generateKML } from '../utilities/missionConfigUtilities';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faDownload, faPrint } from '@fortawesome/free-solid-svg-icons';
import OriginModal from './OriginModal';
import '../styles/BriefingExport.css';

const BriefingExport = ({ configData, originLat, originLon, setOriginLat, setOriginLon }) => {
  const [showOriginModal, setShowOriginModal] = useState(false);

  // ... (existing code remains the same)

  return (
    <div className="briefing-export-container">
      {/* Buttons for Exporting to KML and Printing Mission Briefing */}
      <div className="briefing-actions">
        <button className="export-kml" onClick={exportToKML} title="Export drone positions to KML">
          <FontAwesomeIcon icon={faDownload} /> Export to Google Earth (KML)
        </button>
        <button className="print-mission" onClick={handlePrint} title="Print the mission briefing">
          <FontAwesomeIcon icon={faPrint} /> Print Mission Briefing
        </button>
      </div>

      {/* Origin Modal */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
        />
      )}
    </div>
  );
};

export default BriefingExport;
