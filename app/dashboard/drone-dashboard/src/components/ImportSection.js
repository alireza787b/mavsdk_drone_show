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

const ProcessingProgressModal = ({ isOpen, progress, onClose, isCompleted, onContinue }) => (
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
      p: 4,
      '@keyframes checkPulse': {
        '0%': { transform: 'scale(0.8)', opacity: 0.8 },
        '50%': { transform: 'scale(1.1)', opacity: 1 },
        '100%': { transform: 'scale(1)', opacity: 1 }
      },
      '@keyframes fadeInRight': {
        '0%': { transform: 'translateX(10px)', opacity: 0 },
        '100%': { transform: 'translateX(0)', opacity: 1 }
      },
      '@keyframes spin': {
        '0%': { transform: 'rotate(0deg)' },
        '100%': { transform: 'rotate(360deg)' }
      },
      '@keyframes modalSlideIn': {
        '0%': { transform: 'translate(-50%, -60%) scale(0.95)', opacity: 0 },
        '100%': { transform: 'translate(-50%, -50%) scale(1)', opacity: 1 }
      },
      animation: 'modalSlideIn 0.3s ease-out'
    }}>
      <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Psychology color="primary" />
        {isCompleted ? 'Processing Complete!' : 'Processing Drone Show'}
      </Typography>
      
      <Box sx={{ position: 'relative', mb: 3 }}>
        <LinearProgress 
          variant="determinate" 
          value={progress.overall} 
          sx={{ 
            height: 10, 
            borderRadius: 5,
            backgroundColor: '#e9ecef',
            '& .MuiLinearProgress-bar': {
              backgroundColor: isCompleted ? '#28a745' : '#667eea',
              borderRadius: 5,
              background: isCompleted 
                ? 'linear-gradient(90deg, #28a745 0%, #20c997 100%)'
                : 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)',
              animation: !isCompleted ? 'progressPulse 2s ease-in-out infinite' : 'none',
            },
            '@keyframes progressPulse': {
              '0%': { opacity: 0.8 },
              '50%': { opacity: 1 },
              '100%': { opacity: 0.8 }
            }
          }}
        />
        {!isCompleted && (
          <Box sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '100%',
            background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%)',
            animation: 'progressShimmer 2s infinite',
            borderRadius: 5,
            '@keyframes progressShimmer': {
              '0%': { transform: 'translateX(-100%)' },
              '100%': { transform: 'translateX(100%)' }
            }
          }} />
        )}
      </Box>
      
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
                  <CheckCircle color="success" sx={{ fontSize: 20, animation: 'checkPulse 0.6s ease-out' }} />
                ) : (
                  <CircularProgress size={16} color="primary" sx={{ animation: 'spin 1s linear infinite' }} />
                )}
                <Typography variant="body2" sx={{ 
                  flex: 1, 
                  color: detail.completed ? 'success.main' : 'text.primary',
                  fontWeight: detail.completed ? 600 : 400
                }}>
                  {detail.step}
                </Typography>
                {detail.completed && (
                  <Chip 
                    label="✓" 
                    size="small" 
                    color="success" 
                    sx={{ 
                      minWidth: 32,
                      animation: 'fadeInRight 0.3s ease-out'
                    }}
                  />
                )}
              </Box>
            </ListItem>
          ))}
        </List>
      )}

      {/* Show Continue button when processing is complete */}
      {isCompleted && (
        <Box sx={{ mt: 3, textAlign: 'center' }}>
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

      {/* Show real-time status when processing */}
      {!isCompleted && progress.overall > 0 && (
        <Box sx={{ mt: 2, textAlign: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, mb: 1 }}>
            <CircularProgress size={16} color="primary" />
            <Typography variant="caption" color="primary" sx={{ fontWeight: 'medium' }}>
              {progress.stage.includes('Backend') 
                ? 'Backend processing - this may take several minutes...'
                : progress.stage.includes('Deploying')
                ? 'Deploying to git repository - this can take a few minutes longer...'
                : 'Processing in progress...'}
            </Typography>
          </Box>
          {progress.stage.includes('Deploying') && (
            <Typography variant="caption" color="textSecondary" sx={{ fontStyle: 'italic', fontSize: '0.7rem' }}>
              Committing and pushing changes to cloud repository
            </Typography>
          )}
        </Box>
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
  const [isProcessingCompleted, setIsProcessingCompleted] = useState(false);

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
      { step: 'Updating configuration', completed: false },
      { step: 'Backend processing and analysis', completed: false },
      { step: 'Deploying to cloud repository', completed: false }
    ];

    setProcessingProgress({
      overall: 2,
      stage: 'Initializing upload...',
      details: steps
    });

    let currentStep = 0;
    const interval = setInterval(() => {
      if (currentStep < steps.length - 2) {  // Stop before backend processing
        const updatedSteps = steps.map((step, idx) => ({
          ...step,
          completed: idx < currentStep
        }));

        // Much slower progress - only advance 10% every 2 seconds for first 6 steps
        const baseProgress = (currentStep / (steps.length - 2)) * 60 + 2;
        
        setProcessingProgress({
          overall: Math.min(baseProgress, 65),
          stage: steps[currentStep]?.step + '...',
          details: updatedSteps
        });

        currentStep++;
      } else if (currentStep === steps.length - 2) {
        // Backend processing step - stay here longer
        const updatedSteps = steps.map((step, idx) => ({
          ...step,
          completed: idx < currentStep
        }));

        setProcessingProgress({
          overall: 75,
          stage: 'Backend processing and analysis - this may take several minutes...',
          details: updatedSteps
        });
        
        currentStep++;
      } else {
        // Final step - deployment
        clearInterval(interval);
        const updatedSteps = steps.map((step, idx) => ({
          ...step,
          completed: idx < steps.length - 1 // All except deployment
        }));

        setProcessingProgress({
          overall: 85,
          stage: 'Deploying to cloud repository...',
          details: updatedSteps
        });
      }
    }, 2500); // Much slower progression - 2.5 seconds per step

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
    setIsProcessingCompleted(false);
    
    // Start progress simulation
    const progressInterval = simulateProgressSteps();

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getBackendURL()}/import-show`);

    xhr.onload = () => {
      clearInterval(progressInterval);
      
      if (xhr.status === 200) {
        try {
          const result = JSON.parse(xhr.responseText);
          if (result.success) {
            // Set completion state
            setProcessingProgress({
              overall: 100,
              stage: 'All processing completed successfully!',
              details: [
                { step: 'Extracting ZIP file', completed: true },
                { step: 'Converting coordinates (Blender → NED)', completed: true },
                { step: 'Interpolating trajectories', completed: true },
                { step: 'Calculating comprehensive metrics', completed: true },
                { step: 'Generating 3D visualizations', completed: true },
                { step: 'Updating configuration', completed: true },
                { step: 'Backend processing and analysis', completed: true },
                { step: 'Deploying to cloud repository', completed: true }
              ]
            });
            
            setIsProcessingCompleted(true);
            setIsUploading(false);
          } else {
            setProcessingProgress({
              overall: 0,
              stage: `Processing failed: ${result.error || 'Unknown error'}`,
              details: [{ step: result.error || 'Upload failed - please check file format and try again', completed: false }]
            });
            setIsUploading(false);
          }
        } catch (error) {
          console.error('Error parsing response:', error);
          setProcessingProgress({
            overall: 0,
            stage: 'Processing failed!',
            details: [{ step: 'Invalid server response', completed: false }]
          });
          setIsUploading(false);
        }
      } else {
        setProcessingProgress({
          overall: 0,
          stage: 'Processing failed!',
          details: [{ step: 'Network error occurred', completed: false }]
        });
        setIsUploading(false);
      }
    };

    xhr.onerror = () => {
      clearInterval(progressInterval);
      setProcessingProgress({
        overall: 0,
        stage: 'Processing failed!',
        details: [{ step: 'Network connection failed', completed: false }]
      });
      setIsUploading(false);
    };

    xhr.send(formData);
  };

  const handleContinue = () => {
    setShowProgressModal(false);
    setIsProcessingCompleted(false);
    toast.success('🎯 Drone show processed successfully!');
    setUploadCount((prev) => prev + 1);
    setSelectedFile(null);
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
        isCompleted={isProcessingCompleted}
        onClose={() => setShowProgressModal(false)}
        onContinue={handleContinue}
      />
    </Box>
  );
};

export default ImportSection;
