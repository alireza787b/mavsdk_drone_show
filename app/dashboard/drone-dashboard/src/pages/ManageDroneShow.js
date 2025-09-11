// src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import { Container, Box, Typography, Paper, Button, Modal, LinearProgress, List, ListItem, ListItemIcon, ListItemText, Chip } from '@mui/material';
import { ToastContainer, toast } from 'react-toastify';
import { useNavigate } from 'react-router-dom';
import { CloudUpload, CheckCircle, Publish } from '@mui/icons-material';
import { getBackendURL } from '../utilities/utilities';
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
        Complete workflow: Create in Blender → Upload here → Verify in Mission Control → Launch
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
          onClick={() => navigate('/mission-control')}
        >
          3. Verify Mission Control
        </Button>
        <Button 
          variant="outlined" 
          sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
        >
          4. Launch Show
        </Button>
      </Box>
    </Paper>
  );
};

const DeployProgressModal = ({ isOpen, progress, onClose, onContinue, isCompleted }) => (
  <Modal open={isOpen} onClose={isCompleted ? onClose : () => {}}>
    <Box sx={{
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      width: 500,
      bgcolor: 'background.paper',
      borderRadius: 2,
      boxShadow: 24,
      p: 4
    }}>
      <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Publish color="primary" />
        {isCompleted ? 'Deployment Complete!' : 'Deploying to Drone Fleet'}
      </Typography>
      
      <LinearProgress 
        variant="determinate" 
        value={progress.overall} 
        sx={{ 
          mb: 2, 
          height: 8, 
          borderRadius: 4,
          '& .MuiLinearProgress-bar': {
            backgroundColor: isCompleted ? '#28a745' : '#ff9800'
          }
        }}
      />
      
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="body2" color="textSecondary">
          {progress.stage}
        </Typography>
        <Typography variant="body2" fontWeight="bold">
          {`${Math.round(progress.overall)}%`}
        </Typography>
      </Box>

      {progress.details && (
        <List dense>
          {progress.details.map((detail, idx) => (
            <ListItem key={idx} sx={{ py: 0.5 }}>
              <ListItemIcon sx={{ minWidth: 30 }}>
                {detail.completed ? (
                  <CheckCircle color="success" sx={{ fontSize: 20 }} />
                ) : (
                  <Publish color="primary" sx={{ fontSize: 20 }} />
                )}
              </ListItemIcon>
              <ListItemText 
                primary={detail.step}
                primaryTypographyProps={{ variant: 'body2' }}
              />
              {detail.completed && (
                <Chip label="Done" size="small" color="success" variant="outlined" />
              )}
            </ListItem>
          ))}
        </List>
      )}

      {isCompleted && (
        <Box sx={{ mt: 3, textAlign: 'center' }}>
          <Typography variant="body2" color="success.main" sx={{ mb: 2 }}>
            All drones will receive updates on next boot
          </Typography>
          <Button
            variant="contained"
            onClick={onContinue}
            sx={{
              bgcolor: '#28a745',
              '&:hover': { bgcolor: '#218838' },
              px: 4,
              py: 1.5
            }}
          >
            Continue
          </Button>
        </Box>
      )}

      {!isCompleted && progress.overall > 0 && (
        <Box sx={{ mt: 2, textAlign: 'center' }}>
          <Typography variant="caption" color="textSecondary" sx={{ fontStyle: 'italic' }}>
            Pushing changes to git repository... Please wait
          </Typography>
        </Box>
      )}
    </Box>
  </Modal>
);

const ManageDroneShow = () => {
  const [uploadCount, setUploadCount] = useState(0);
  const [showDeployModal, setShowDeployModal] = useState(false);
  const [deployProgress, setDeployProgress] = useState({ overall: 0, stage: '', details: [] });
  const [isDeployCompleted, setIsDeployCompleted] = useState(false);

  const handleDeploy = async () => {
    setShowDeployModal(true);
    setIsDeployCompleted(false);
    
    const steps = [
      { step: 'Preparing changes for deployment', completed: false },
      { step: 'Committing show data to repository', completed: false },
      { step: 'Pushing to remote repository', completed: false },
      { step: 'Updating drone fleet configuration', completed: false }
    ];

    setDeployProgress({
      overall: 10,
      stage: 'Starting deployment...',
      details: steps
    });

    try {
      // Simulate deployment progress
      for (let i = 0; i < steps.length; i++) {
        const updatedSteps = steps.map((step, idx) => ({
          ...step,
          completed: idx <= i
        }));

        setDeployProgress({
          overall: 25 + (i * 20),
          stage: steps[i].step + '...',
          details: updatedSteps
        });

        await new Promise(resolve => setTimeout(resolve, 1500));
      }

      // Call backend deploy endpoint
      const response = await fetch(`${getBackendURL()}/deploy-show`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: `Deploy drone show: ${new Date().toISOString()}` })
      });

      if (response.ok) {
        setDeployProgress({
          overall: 100,
          stage: 'Deployment completed successfully!',
          details: steps.map(step => ({ ...step, completed: true }))
        });
        setIsDeployCompleted(true);
      } else {
        throw new Error('Deployment failed');
      }
    } catch (error) {
      console.error('Deploy error:', error);
      setDeployProgress({
        overall: 0,
        stage: 'Deployment failed!',
        details: [{ step: 'Error: ' + error.message, completed: false }]
      });
    }
  };

  const handleDeployContinue = () => {
    setShowDeployModal(false);
    setIsDeployCompleted(false);
    toast.success('🚀 Drone show deployed successfully! All drones will receive updates on next boot.');
  };

  return (
    <Container maxWidth="97%" className="manage-drone-show-container">
      <ToastContainer />
      
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: 3, mb: 2 }}>
        <Typography variant="h4" sx={{ color: '#0056b3' }}>
          Manage Drone Show
        </Typography>
        
        {/* Deploy Button */}
        <Button
          variant="contained"
          onClick={handleDeploy}
          startIcon={<Publish />}
          sx={{
            bgcolor: '#ff9800',
            '&:hover': { bgcolor: '#f57c00' },
            color: 'white',
            fontWeight: 'bold',
            px: 3,
            py: 1.5,
            boxShadow: '0 4px 12px rgba(255, 152, 0, 0.3)',
            borderRadius: 2
          }}
        >
          Deploy to Fleet
        </Button>
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

      {/* Deploy Progress Modal */}
      <DeployProgressModal
        isOpen={showDeployModal}
        progress={deployProgress}
        isCompleted={isDeployCompleted}
        onClose={() => setShowDeployModal(false)}
        onContinue={handleDeployContinue}
      />
    </Container>
  );
};

export default ManageDroneShow;
