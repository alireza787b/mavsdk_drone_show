// src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import { Container, Box, Typography, Paper, Button, Collapse } from '@mui/material';
import { ToastContainer } from 'react-toastify';
import { useNavigate } from 'react-router-dom';
import { ExpandMore, ExpandLess } from '@mui/icons-material';
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
        🚁 Drone Show Design Workflow
      </Typography>
      <Typography variant="body2" sx={{ mb: 2, opacity: 0.9 }}>
        Follow this workflow for optimal drone show development
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Button 
          variant="outlined" 
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
          onClick={() => navigate('/trajectory-planning')}
        >
          1. Design Trajectory
        </Button>
        <Button 
          variant="contained" 
          sx={{ 
            bgcolor: 'rgba(255,255,255,0.2)', 
            color: 'white',
            '&:hover': { bgcolor: 'rgba(255,255,255,0.3)' }
          }}
        >
          2. Import & Process Show ← You are here
        </Button>
        <Button 
          variant="outlined" 
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
          onClick={() => navigate('/swarm-trajectory')}
        >
          3. Configure Swarm
        </Button>
      </Box>
    </Paper>
  );
};

const ManageDroneShow = () => {
  const [uploadCount, setUploadCount] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <Container maxWidth="97%" className="manage-drone-show-container">
      <ToastContainer />
      
      <Typography variant="h4" align="center" gutterBottom sx={{ mt: 3, color: '#0056b3' }}>
        Manage Drone Show
      </Typography>

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

      {/* Advanced Features Toggle */}
      <Paper elevation={1} sx={{ p: 2, mb: 3, bgcolor: '#f8f9fa' }}>
        <Button
          onClick={() => setShowAdvanced(!showAdvanced)}
          sx={{ 
            color: '#0056b3', 
            fontWeight: 'bold',
            '&:hover': { bgcolor: 'rgba(0, 86, 179, 0.1)' }
          }}
          endIcon={showAdvanced ? <ExpandLess /> : <ExpandMore />}
        >
          {showAdvanced ? 'Hide Advanced Features' : 'Show Advanced Features'}
        </Button>
        
        <Collapse in={showAdvanced}>
          <Box sx={{ mt: 2 }}>
            <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
              <ExportSection />
            </Paper>
          </Box>
        </Collapse>
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
