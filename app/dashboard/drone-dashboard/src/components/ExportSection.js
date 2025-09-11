// src/components/ExportSection.js
import React from 'react';
import { getBackendURL } from '../utilities/utilities';
import { Box, Typography, Button, Paper } from '@mui/material';

const ExportSection = () => {
  const handleDownload = (type) => {
    const downloadUrl = `${getBackendURL()}/download-${type}-show`;
    window.open(downloadUrl, '_blank');
  };

  return (
    <Box className="export-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Export & Download
      </Typography>

      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Button variant="contained" onClick={() => handleDownload('raw')}>
            Download Raw Show
          </Button>
          <Button variant="contained" onClick={() => handleDownload('processed')}>
            Download Processed Show
          </Button>

          <Typography variant="body2" sx={{ mt: 1 }} className="info">
            Use the buttons above to download the raw or processed data for your drone shows. 
            Raw data contains the original ZIP file created by SkyBrush, while processed data 
            includes modifications for MAVSDK Drone Show.
          </Typography>
        </Box>
      </Paper>
    </Box>
  );
};

export default ExportSection;
