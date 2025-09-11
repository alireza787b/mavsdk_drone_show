// src/components/ImportSection.js
import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import '../styles/ImportSection.css';
import { 
  Button, 
  CircularProgress, 
  Typography, 
  Box, 
  Paper, 
  List, 
  ListItem, 
  ListItemText, 
  Link,
  Modal,
  LinearProgress,
  Chip,
  Divider
} from '@mui/material';
import { 
  CloudUpload, 
  CheckCircle, 
  Psychology,
  Timeline,
  Security,
  Assessment
} from '@mui/icons-material';

const ProcessingProgressModal = ({ isOpen, progress, onClose }) => (
  <Modal open={isOpen} onClose={onClose}>
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
        <Psychology color="primary" />
        Processing Drone Show
      </Typography>
      
      <LinearProgress 
        variant="determinate" 
        value={progress.overall} 
        sx={{ mb: 2, height: 8, borderRadius: 4 }}
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
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                {detail.completed ? (
                  <CheckCircle color="success" sx={{ fontSize: 20 }} />
                ) : (
                  <CircularProgress size={20} />
                )}
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {detail.step}
                </Typography>
                {detail.completed && (
                  <Chip label="Done" size="small" color="success" variant="outlined" />
                )}
              </Box>
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  </Modal>
);

const ImportSection = ({ setUploadCount }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [processingProgress, setProcessingProgress] = useState({
    overall: 0,
    stage: '',
    details: []
  });
  const [showProgressModal, setShowProgressModal] = useState(false);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) {
      toast.warn('No file selected. Please choose a file.');
      return;
    }
    if (!file.name.endsWith('.zip')) {
      toast.error('Invalid file type. Please select a ZIP file.');
      return;
    }
    setSelectedFile(file);
  };

  const simulateProgressSteps = () => {
    const steps = [
      { step: 'Extracting ZIP file', completed: false },
      { step: 'Converting coordinates (Blender → NED)', completed: false },
      { step: 'Interpolating trajectories', completed: false },
      { step: 'Calculating comprehensive metrics', completed: false },
      { step: 'Generating 3D visualizations', completed: false },
      { step: 'Updating configuration', completed: false }
    ];

    setProcessingProgress({
      overall: 10,
      stage: 'Starting processing...',
      details: steps
    });

    let currentStep = 0;
    const interval = setInterval(() => {
      currentStep++;
      const newProgress = (currentStep / steps.length) * 90 + 10;
      
      const updatedSteps = steps.map((step, idx) => ({
        ...step,
        completed: idx < currentStep
      }));

      setProcessingProgress({
        overall: newProgress,
        stage: currentStep <= steps.length ? steps[currentStep - 1]?.step : 'Finalizing...',
        details: updatedSteps
      });

      if (currentStep >= steps.length) {
        clearInterval(interval);
        setTimeout(() => {
          setProcessingProgress(prev => ({ ...prev, overall: 100, stage: 'Processing complete!' }));
        }, 500);
      }
    }, 800);

    return interval;
  };

  const uploadFile = () => {
    if (!selectedFile) {
      toast.warn('Please select a file to upload.');
      return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);

    setIsUploading(true);
    setShowProgressModal(true);
    
    const progressInterval = simulateProgressSteps();

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getBackendURL()}/import-show`);

    xhr.onload = () => {
      clearInterval(progressInterval);
      setIsUploading(false);
      
      setTimeout(() => {
        setShowProgressModal(false);
        
        if (xhr.status === 200) {
          try {
            const result = JSON.parse(xhr.responseText);
            if (result.success) {
              toast.success('🎯 File processed successfully with comprehensive analysis!');
              setUploadCount((prev) => prev + 1);
              setSelectedFile(null);
            } else {
              toast.error(result.error || 'Unknown error during file upload.');
            }
          } catch (error) {
            console.error('Error parsing response:', error);
            toast.error('Invalid server response.');
          }
        } else {
          toast.error('Network error. Please try again.');
        }
      }, 1000);
    };

    xhr.onerror = () => {
      clearInterval(progressInterval);
      setIsUploading(false);
      setShowProgressModal(false);
      toast.error('Network error. Please try again.');
    };

    xhr.send(formData);
  };

  return (
    <Box className="import-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Import Drone Show
      </Typography>

      <Box className="intro-section" sx={{ mb: 3 }}>
        <Typography variant="body1" paragraph sx={{ color: '#374151', lineHeight: 1.6 }}>
          🎯 <strong>Professional Drone Show Import & Analysis</strong> - Upload your SkyBrush ZIP files 
          for comprehensive trajectory processing and safety analysis.
        </Typography>
        
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 2, mb: 2 }}>
          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <CloudUpload color="primary" />
              <Typography variant="subtitle2" fontWeight="bold">Smart Upload</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              One-click ZIP processing with automatic format validation
            </Typography>
          </Paper>
          
          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Timeline color="secondary" />
              <Typography variant="subtitle2" fontWeight="bold">Trajectory Analysis</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Advanced interpolation with performance metrics calculation
            </Typography>
          </Paper>
          
          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Security color="success" />
              <Typography variant="subtitle2" fontWeight="bold">Safety Validation</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Real-time collision detection and clearance analysis
            </Typography>
          </Paper>
          
          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Assessment color="info" />
              <Typography variant="subtitle2" fontWeight="bold">Quality Reports</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Formation coherence and performance optimization insights
            </Typography>
          </Paper>
        </Box>

        <Divider sx={{ my: 2 }} />

        <Typography variant="body2" color="textSecondary">
          💡 <strong>Pro Tip:</strong> Use our{' '}
          <Link 
            href="https://youtu.be/wctmCIzpMpY" 
            target="_blank" 
            rel="noreferrer"
            color="primary" 
            underline="hover"
          >
            SkyBrush tutorial
          </Link>{' '}
          to create professional drone show animations in Blender.
        </Typography>
      </Box>

      {/* File Upload Section */}
      <Paper sx={{ p: 2 }}>
        <Box className="file-upload" sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Button variant="outlined" component="label">
            {selectedFile ? selectedFile.name : 'Choose ZIP File'}
            <input
              type="file"
              accept=".zip"
              onChange={handleFileChange}
              hidden
            />
          </Button>
          
          <Button 
            variant="contained" 
            onClick={uploadFile} 
            disabled={!selectedFile || isUploading}
            startIcon={isUploading ? <CircularProgress size={20} color="inherit" /> : <CloudUpload />}
            sx={{ 
              minWidth: 140,
              bgcolor: '#10b981',
              '&:hover': { bgcolor: '#059669' }
            }}
          >
            {isUploading ? 'Processing...' : 'Upload & Analyze'}
          </Button>
        </Box>
      </Paper>

      {/* Processing Progress Modal */}
      <ProcessingProgressModal 
        isOpen={showProgressModal}
        progress={processingProgress}
        onClose={() => !isUploading && setShowProgressModal(false)}
      />
    </Box>
  );
};

export default ImportSection;
