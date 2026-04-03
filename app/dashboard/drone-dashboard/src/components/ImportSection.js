import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  LinearProgress,
  Link,
  List,
  ListItem,
  Modal,
  Paper,
  Typography,
} from '@mui/material';
import {
  Assessment,
  CheckCircle,
  CloudUpload,
  Security,
  Timeline,
  Visibility,
} from '@mui/icons-material';

import { extractApiErrorMessage } from '../services/apiError';
import { importShowResponse } from '../services/gcsApiService';
import '../styles/ImportSection.css';

const PROGRESS_STEPS = [
  'Uploading archive',
  'Validating ZIP structure',
  'Preparing staged drone files',
  'Processing trajectories',
  'Generating plots',
  'Finalizing import',
];

const INITIAL_PROGRESS = {
  overall: 0,
  stage: '',
  details: [],
};

const ProcessingProgressModal = ({
  isOpen,
  progress,
  isCompleted,
  isFailed,
  importResult,
  onClose,
  onStayHere,
  onMissionConfig,
  onOverview,
}) => {
  const canClose = isCompleted || isFailed;

  return (
    <Modal open={isOpen} onClose={canClose ? onClose : undefined}>
      <Box
        sx={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: { xs: '92vw', sm: 560 },
          maxHeight: '88vh',
          overflowY: 'auto',
          bgcolor: 'background.paper',
          borderRadius: 2,
          boxShadow: 24,
          p: 4,
        }}
      >
        <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <CloudUpload color={isFailed ? 'error' : isCompleted ? 'success' : 'primary'} />
          {isCompleted ? 'Drone Show Ready' : isFailed ? 'Import Failed' : 'Processing Drone Show'}
        </Typography>

        <Box sx={{ position: 'relative', mb: 2 }}>
          <LinearProgress
            variant="determinate"
            value={progress.overall}
            color={isFailed ? 'error' : isCompleted ? 'success' : 'primary'}
            sx={{ height: 10, borderRadius: 5 }}
          />
        </Box>

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="body2" color="textSecondary">
            {progress.stage}
          </Typography>
          <Typography variant="body2" fontWeight="bold">
            {`${Math.round(progress.overall)}%`}
          </Typography>
        </Box>

        {!isCompleted && !isFailed && (
          <List dense sx={{ mb: 1 }}>
            {progress.details.map((detail) => (
              <ListItem key={detail.step} sx={{ px: 0, py: 0.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  {detail.completed ? (
                    <CheckCircle color="success" sx={{ fontSize: 20 }} />
                  ) : (
                    <CircularProgress size={16} color="primary" />
                  )}
                  <Typography variant="body2" sx={{ flex: 1 }}>
                    {detail.step}
                  </Typography>
                </Box>
              </ListItem>
            ))}
          </List>
        )}

        {isFailed && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {progress.details[0]?.step || 'Import failed. Please review the archive and try again.'}
          </Alert>
        )}

        {isCompleted && importResult && (
          <>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
              <Chip label={`${importResult.files_processed} drones processed`} color="success" />
              <Chip label={`${importResult.plots_generated} plots generated`} color="info" />
              <Chip label={`${importResult.raw_files_found} raw CSV files`} variant="outlined" />
              {importResult.warnings?.length > 0 && (
                <Chip label={`${importResult.warnings.length} warning${importResult.warnings.length > 1 ? 's' : ''}`} color="warning" />
              )}
            </Box>

            <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: '#f8fafc' }}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700 }}>
                Imported Show
              </Typography>
              <Typography variant="body2" color="textSecondary">
                {importResult.show_name}
              </Typography>
            </Paper>

            {importResult.warnings?.length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Import completed with warnings
                </Typography>
                <List dense sx={{ py: 0 }}>
                  {importResult.warnings.map((warning) => (
                    <ListItem key={warning} sx={{ display: 'list-item', py: 0.25 }}>
                      <Typography variant="body2">{warning}</Typography>
                    </ListItem>
                  ))}
                </List>
              </Alert>
            )}

            {importResult.next_steps?.length > 0 && (
              <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
                <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700 }}>
                  Next Operator Steps
                </Typography>
                <List dense sx={{ py: 0 }}>
                  {importResult.next_steps.map((step) => (
                    <ListItem key={step} sx={{ display: 'list-item', py: 0.25 }}>
                      <Typography variant="body2">{step}</Typography>
                    </ListItem>
                  ))}
                </List>
              </Paper>
            )}
          </>
        )}

        {isCompleted && (
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Button variant="outlined" onClick={onStayHere}>
              Stay Here
            </Button>
            <Button variant="outlined" onClick={onOverview}>
              Open Overview
            </Button>
            <Button variant="contained" onClick={onMissionConfig}>
              Review Mission Config
            </Button>
          </Box>
        )}

        {isFailed && (
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button variant="contained" color="primary" onClick={onClose}>
              Close
            </Button>
          </Box>
        )}
      </Box>
    </Modal>
  );
};

const ImportSection = ({ setUploadCount }) => {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(INITIAL_PROGRESS);
  const [showProgressModal, setShowProgressModal] = useState(false);
  const [isProcessingCompleted, setIsProcessingCompleted] = useState(false);
  const [isProcessingFailed, setIsProcessingFailed] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const progressTemplate = useMemo(
    () => PROGRESS_STEPS.map((step) => ({ step, completed: false })),
    []
  );

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      toast.warn('No file selected. Please choose a ZIP archive.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.zip')) {
      toast.error('Invalid file type. Please select a ZIP archive.');
      return;
    }
    setSelectedFile(file);
  };

  const startProgressSimulation = () => {
    let currentStep = 0;
    setProcessingProgress({
      overall: 5,
      stage: `${progressTemplate[0].step}...`,
      details: progressTemplate,
    });

    return window.setInterval(() => {
      currentStep = Math.min(currentStep + 1, progressTemplate.length - 1);
      const details = progressTemplate.map((step, index) => ({
        ...step,
        completed: index < currentStep,
      }));
      const overall = Math.min(82, 8 + (currentStep / progressTemplate.length) * 74);
      setProcessingProgress({
        overall,
        stage: `${progressTemplate[currentStep].step}...`,
        details,
      });
    }, 900);
  };

  const closeModal = () => {
    setShowProgressModal(false);
    setIsProcessingCompleted(false);
    setIsProcessingFailed(false);
    setProcessingProgress(INITIAL_PROGRESS);
    setImportResult(null);
  };

  const handleStayHere = () => {
    closeModal();
    setSelectedFile(null);
    toast.success('Drone show import completed.');
  };

  const handleGoToMissionConfig = () => {
    closeModal();
    setSelectedFile(null);
    navigate('/mission-config');
  };

  const handleGoToOverview = () => {
    closeModal();
    setSelectedFile(null);
    navigate('/mission-control');
  };

  const uploadFile = async () => {
    if (!selectedFile) {
      toast.warn('Please select a ZIP file first.');
      return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);

    setIsUploading(true);
    setShowProgressModal(true);
    setIsProcessingCompleted(false);
    setIsProcessingFailed(false);
    setImportResult(null);

    const progressInterval = startProgressSimulation();

    try {
      const response = await importShowResponse(formData);
      const payload = response.data || {};
      if (!payload.success) {
        throw new Error(payload.detail || payload.error || payload.message || 'Show import failed');
      }

      window.clearInterval(progressInterval);
      setImportResult(payload);
      setProcessingProgress({
        overall: 100,
        stage: payload.warnings?.length
          ? 'Import complete with warnings'
          : 'Import complete and ready for verification',
        details: progressTemplate.map((step) => ({ ...step, completed: true })),
      });
      setIsProcessingCompleted(true);
      setUploadCount((count) => count + 1);
    } catch (error) {
      window.clearInterval(progressInterval);
      const message = await extractApiErrorMessage(error, 'Unexpected import failure');
      setProcessingProgress({
        overall: 0,
        stage: 'Import failed',
        details: [{ step: message, completed: false }],
      });
      setIsProcessingFailed(true);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Box className="import-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Import Drone Show
      </Typography>

      <Box className="intro-section" sx={{ mb: 3 }}>
        <Typography variant="body1" paragraph sx={{ color: '#374151', lineHeight: 1.6 }}>
          Upload a SkyBrush ZIP archive to generate the processed Drone Show CSV set, launch plots,
          and operator-facing verification data.
        </Typography>
        <Alert severity="info" sx={{ mb: 2 }}>
          Standard Drone Show only. If you already authored one protocol-correct CSV that every drone should replay
          from its own local launch frame, use <strong>Custom Show</strong> instead of this page.
        </Alert>

        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 2, mb: 2 }}>
          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <CloudUpload color="primary" />
              <Typography variant="subtitle2" fontWeight="bold">Staged Import</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              The archive is validated before it replaces the current active show.
            </Typography>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Timeline color="secondary" />
              <Typography variant="subtitle2" fontWeight="bold">Trajectory Processing</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              SkyBrush CSVs are converted into the processed NED flight files used by Drone Show missions.
            </Typography>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Security color="success" />
              <Typography variant="subtitle2" fontWeight="bold">Operator Verification</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              After import, verify mission config, origin, and readiness before launch.
            </Typography>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, bgcolor: '#f8f9fa' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Visibility color="info" />
              <Typography variant="subtitle2" fontWeight="bold">Plot Review</Typography>
            </Box>
            <Typography variant="body2" color="textSecondary">
              Combined and per-drone plots are refreshed automatically after a successful import.
            </Typography>
          </Paper>
        </Box>

        <Divider sx={{ my: 2 }} />

        <Typography variant="body2" color="textSecondary">
          Use our{' '}
          <Link href="https://youtu.be/wctmCIzpMpY" target="_blank" rel="noreferrer" color="primary" underline="hover">
            SkyBrush tutorial
          </Link>{' '}
          to create Blender/SkyBrush ZIP exports. After import, continue to{' '}
          <Link component="button" type="button" onClick={() => navigate('/mission-config')} underline="hover">
            Mission Config
          </Link>{' '}
          for final launch-position review.
        </Typography>
      </Box>

      <Paper sx={{ p: 2 }}>
        <Box className="file-upload" sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Button variant="outlined" component="label">
            {selectedFile ? selectedFile.name : 'Choose ZIP File'}
            <input type="file" accept=".zip" onChange={handleFileChange} hidden />
          </Button>

          <Button
            variant="contained"
            onClick={uploadFile}
            disabled={!selectedFile || isUploading}
            startIcon={isUploading ? <CircularProgress size={20} color="inherit" /> : <CloudUpload />}
            sx={{
              minWidth: 160,
              bgcolor: '#10b981',
              '&:hover': { bgcolor: '#059669' },
            }}
          >
            {isUploading ? 'Importing...' : 'Upload & Process'}
          </Button>

          {selectedFile && (
            <Chip
              icon={<Assessment />}
              label="SkyBrush ZIP selected"
              variant="outlined"
              color="primary"
            />
          )}
        </Box>
      </Paper>

      <ProcessingProgressModal
        isOpen={showProgressModal}
        progress={processingProgress}
        isCompleted={isProcessingCompleted}
        isFailed={isProcessingFailed}
        importResult={importResult}
        onClose={closeModal}
        onStayHere={handleStayHere}
        onMissionConfig={handleGoToMissionConfig}
        onOverview={handleGoToOverview}
      />
    </Box>
  );
};

export default ImportSection;
