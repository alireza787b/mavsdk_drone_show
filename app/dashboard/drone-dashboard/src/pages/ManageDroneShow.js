// src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import { Container, Box, Typography, Paper, Button } from '@mui/material';
import { ToastContainer } from 'react-toastify';
import { useNavigate } from 'react-router-dom';
import ImportSection from '../components/ImportSection';
import ExportSection from '../components/ExportSection';
import VisualizationSection from '../components/VisualizationSection';
import '../styles/ManageDroneShow.css';

const WorkflowGuidanceSection = () => {
  const navigate = useNavigate();
  
  return (
    <Paper 
      elevation={3} 
      sx={{ 
        p: 2, 
        mb: 3, 
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        color: 'white'
      }}
    >
      <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold' }}>
        🎬 Drone Show Production Workflow
      </Typography>
      <Typography variant="body2" sx={{ mb: 2, color: 'white', fontWeight: 500 }}>
        Create in Blender / SkyBrush, import here, verify launch geometry in Mission Config, then confirm live readiness in Overview before launch.
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Button
          variant="outlined"
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
        >
          1. Create in Blender/SkyBrush
        </Button>
        <Button 
          variant="contained" 
          sx={{ 
            bgcolor: 'rgba(255,255,255,0.2)', 
            color: 'white',
            '&:hover': { bgcolor: 'rgba(255,255,255,0.3)' }
          }}
        >
          2. Upload & Process ← You are here
        </Button>
        <Button
          variant="outlined"
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
          onClick={() => navigate('/mission-config')}
        >
          3. Review Mission Config
        </Button>
        <Button
          variant="outlined"
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
          onClick={() => navigate('/mission-control')}
        >
          4. Confirm Overview
        </Button>
        <Button
          variant="outlined"
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
        >
          5. Launch Show
        </Button>
      </Box>
    </Paper>
  );
};


const ManageDroneShow = () => {
  const [uploadCount, setUploadCount] = useState(0);


  return (
    <Container maxWidth="97%" className="manage-drone-show-container">
      <ToastContainer />
      
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', mt: 3, mb: 2 }}>
        <Typography variant="h4" sx={{ color: '#0056b3' }}>
          Manage Drone Show
        </Typography>
      </Box>

      {/* Workflow Guidance */}
      <WorkflowGuidanceSection />

      {/* Import Section - Always Visible */}
      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <ImportSection setUploadCount={setUploadCount} />
      </Paper>

      {/* Visualization Section - Always Visible */}
      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <VisualizationSection uploadCount={uploadCount} />
      </Paper>

      {/* Export Options */}
      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <ExportSection />
      </Paper>

      {/* Footer */}
      <Box textAlign="center" sx={{ mt: 4, mb: 2 }}>
        <Typography variant="body2" color="textSecondary">
          &copy; {new Date().getFullYear()} Drone Show Management System. All rights reserved.
        </Typography>
      </Box>

    </Container>
  );
};

export default ManageDroneShow;
