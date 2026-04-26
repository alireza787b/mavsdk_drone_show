// app/dashboard/drone-dashboard/src/components/BriefingExport.js

import React, { useState } from 'react';
import { generateKML } from '../utilities/missionConfigUtilities';
import { FaDownload, FaPrint } from 'react-icons/fa';
import OriginModal from './OriginModal';
import { ActionIconButton } from './ui/OperatorPrimitives';
import '../styles/BriefingExport.css';

const BriefingExport = ({ configData, originLat, originLon, setOriginLat, setOriginLon }) => {
  const [showOriginModal, setShowOriginModal] = useState(false);

  // Handle printing the mission briefing
  const handlePrint = () => {
    window.print();
  };

  // Export the drone positions to a KML file for Google Earth
  const exportToKML = () => {
    if (!originLat || !originLon) {
      setShowOriginModal(true);
      return;
    }

    if (isNaN(originLat) || isNaN(originLon)) {
      alert('Origin latitude and longitude must be valid numbers.');
      return;
    }

    const kmlContent = generateKML(configData, originLat, originLon);
    const blob = new Blob([kmlContent], { type: 'application/vnd.google-earth.kml+xml' });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;
    link.download = 'drone_positions.kml';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOriginSubmit = (lat, lon) => {
    setOriginLat(lat);
    setOriginLon(lon);
    setShowOriginModal(false);
    // Proceed to generate KML now that we have originLat and originLon
    exportToKML();
  };

  return (
    <div className="briefing-export-container">
      {/* Buttons for Exporting to KML and Printing Mission Briefing */}
      <div className="briefing-actions">
        <ActionIconButton
          icon={<FaDownload />}
          label="Export drone positions to KML"
          tone="info"
          onClick={exportToKML}
          data-help="Export drone positions to KML"
        >
          KML
        </ActionIconButton>
        <ActionIconButton
          icon={<FaPrint />}
          label="Print mission briefing"
          onClick={handlePrint}
          data-help="Print the mission briefing"
        >
          Print
        </ActionIconButton>
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
