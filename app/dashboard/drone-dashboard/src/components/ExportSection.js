// src/components/ExportSection.js
import React from 'react';
import { Box, Typography, Button, Paper, Alert } from '@mui/material';
import useFetch from '../hooks/useFetch';
import {
  buildShowDownloadUrl,
  GCS_ROUTE_KEYS,
} from '../services/gcsApiService';

const ExportSection = () => {
  const { data: showInfo } = useFetch(GCS_ROUTE_KEYS.showInfo);
  const hasImportedShow = Boolean(showInfo && Number(showInfo.drone_count) > 0);

  const handleDownload = (type) => {
    if (!hasImportedShow) {
      return;
    }
    const downloadUrl = buildShowDownloadUrl(type);
    window.open(downloadUrl, '_blank');
  };

  return (
    <Box className="export-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Export & Download
      </Typography>

      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {!hasImportedShow && (
            <Alert severity="info">
              Import a Drone Show first to enable raw and processed export packages.
            </Alert>
          )}

          <Button variant="contained" onClick={() => handleDownload('raw')} disabled={!hasImportedShow}>
            Download Raw Show
          </Button>
          <Button variant="contained" onClick={() => handleDownload('processed')} disabled={!hasImportedShow}>
            Download Processed Show
          </Button>

          <Typography variant="body2" sx={{ mt: 1 }} className="info">
            Raw export contains the current SkyBrush CSV set stored on the GCS. Processed export
            contains the NED trajectory files used by Drone Show missions.
          </Typography>
        </Box>
      </Paper>
    </Box>
  );
};

export default ExportSection;
