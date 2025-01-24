// src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import { Container, Box, Typography, Paper } from '@mui/material';
import { ToastContainer } from 'react-toastify';
import ImportSection from '../components/ImportSection';
import ExportSection from '../components/ExportSection';
import VisualizationSection from '../components/VisualizationSection';
import '../styles/ManageDroneShow.css';

const ManageDroneShow = () => {
  const [uploadCount, setUploadCount] = useState(0);

  return (
    <Container maxWidth="97%" className="manage-drone-show-container">
      <ToastContainer />
      
      <Typography variant="h4" align="center" gutterBottom sx={{ mt: 3, color: '#0056b3' }}>
        Manage Drone Show
      </Typography>

      {/* Main Paper Container for overall structure */}
      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <ImportSection setUploadCount={setUploadCount} />
      </Paper>

      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <ExportSection />
      </Paper>

      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <VisualizationSection uploadCount={uploadCount} />
      </Paper>

      {/* Footer or Additional Info */}
      <Box textAlign="center" sx={{ mt: 4, mb: 2 }}>
        <Typography variant="body2" color="textSecondary">
          &copy; {new Date().getFullYear()} Drone Show Management System. All rights reserved.
        </Typography>
      </Box>
    </Container>
  );
};

export default ManageDroneShow;
