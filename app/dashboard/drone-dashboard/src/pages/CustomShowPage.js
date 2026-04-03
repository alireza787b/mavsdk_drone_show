import React, { useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import {
  CloudUpload,
  Description,
  FlightTakeoff,
  Insights,
  Route,
  RuleFolder,
  Visibility,
} from '@mui/icons-material';

import useFetch from '../hooks/useFetch';
import { extractApiErrorMessage } from '../services/apiError';
import {
  buildGcsUrl,
  GCS_ROUTE_KEYS,
  importCustomShowResponse,
} from '../services/gcsApiService';
import '../styles/CustomShowPage.css';

const CUSTOM_SHOW_DOC_URL = 'https://github.com/alireza787b/mavsdk_drone_show/blob/main-candidate/docs/features/drone-show.md#custom-csv-operational-note';
const FALLBACK_REQUIRED_COLUMNS = ['t', 'px', 'py', 'pz', 'vx', 'vy', 'vz', 'ax', 'ay', 'az', 'yaw', 'mode'];

function formatDuration(durationSec) {
  if (!Number.isFinite(durationSec)) {
    return 'N/A';
  }

  return `${durationSec.toFixed(2)}s`;
}

const CustomShowPage = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [imageLoadFailed, setImageLoadFailed] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [uploadWarnings, setUploadWarnings] = useState([]);

  const { data: customShowInfo, error: customShowError } = useFetch(`${GCS_ROUTE_KEYS.customShowInfo}?refresh=${refreshKey}`);
  const hasActiveCustomShow = Boolean(customShowInfo?.exists);
  const previewAvailable = Boolean(customShowInfo?.preview_exists);
  const requiredColumns = customShowInfo?.required_columns?.length
    ? customShowInfo.required_columns
    : FALLBACK_REQUIRED_COLUMNS;

  const imageSrc = useMemo(
    () => (
      previewAvailable
        ? buildGcsUrl(`${GCS_ROUTE_KEYS.customShowImage}?refresh=${refreshKey}`)
        : null
    ),
    [previewAvailable, refreshKey],
  );

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    if (!file.name.toLowerCase().endsWith('.csv')) {
      toast.error('Custom CSV mode only accepts protocol-compliant CSV files.');
      return;
    }

    setSelectedFile(file);
  };

  const uploadCustomCsv = async () => {
    if (!selectedFile) {
      toast.warn('Choose a custom CSV file first.');
      return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);

    setIsUploading(true);
    setUploadWarnings([]);

    try {
      const response = await importCustomShowResponse(formData);
      const payload = response.data || {};

      if (!payload.success) {
        throw new Error(payload.detail || payload.message || 'Custom CSV upload failed');
      }

      setUploadWarnings(payload.warnings || []);
      setSelectedFile(null);
      setImageLoadFailed(false);
      setRefreshKey((key) => key + 1);
      toast.success('Custom CSV validated and activated.');
    } catch (error) {
      toast.error(await extractApiErrorMessage(error, 'Failed to upload custom CSV.'));
    } finally {
      setIsUploading(false);
    }
  };

  const showMissingCsvAlert = customShowError?.response?.status === 404 && !hasActiveCustomShow;
  const customShowBackendError = !showMissingCsvAlert
    ? customShowError?.response?.data?.detail || customShowError?.message || ''
    : '';

  return (
    <div className="custom-show-page">
      <div className="custom-show-page__hero">
        <div>
          <Typography variant="overline" className="custom-show-page__eyebrow">
            Advanced Manual Mode
          </Typography>
          <Typography variant="h3" className="custom-show-page__title">
            Custom CSV Drone Show
          </Typography>
          <Typography variant="body1" className="custom-show-page__intro">
            Upload one ready-to-execute protocol CSV as <code>active.csv</code>. MDS validates the file,
            regenerates the preview, and then every drone executes that same path relative to its own local
            launch frame.
          </Typography>
        </div>

        <div className="custom-show-page__hero-actions">
          <Button component={RouterLink} to="/drone-show-design" variant="outlined">
            Open Show Design
          </Button>
          <Button component={RouterLink} to="/mission-config" variant="outlined">
            Review Mission Config
          </Button>
        </div>
      </div>

      <Alert severity="warning" className="custom-show-page__banner">
        Expert-only override: no SkyBrush ZIP processing happens here. This page assumes you already authored the
        correct protocol CSV and want every drone to replay the same file in its own local launch frame.
      </Alert>

      {customShowBackendError && (
        <Alert severity="error" className="custom-show-page__banner">
          Failed to load the active custom CSV metadata: {customShowBackendError}
        </Alert>
      )}

      <div className="custom-show-page__grid">
        <Paper className="custom-show-card custom-show-card--upload" elevation={0}>
          <div className="custom-show-card__header">
            <CloudUpload color="primary" />
            <div>
              <Typography variant="h6">Upload Ready-to-Execute CSV</Typography>
              <Typography variant="body2" color="text.secondary">
                Upload replaces the current <code>active.csv</code>, validates the protocol, and regenerates the preview.
              </Typography>
            </div>
          </div>

          <Stack spacing={2}>
            <div className="custom-show-upload-row">
              <Button variant="outlined" component="label">
                {selectedFile ? selectedFile.name : 'Choose CSV File'}
                <input type="file" accept=".csv,text/csv" hidden onChange={handleFileChange} />
              </Button>

              <Button
                variant="contained"
                onClick={uploadCustomCsv}
                disabled={!selectedFile || isUploading}
                startIcon={isUploading ? <CircularProgress size={18} color="inherit" /> : <CloudUpload />}
              >
                {isUploading ? 'Validating...' : 'Upload & Activate'}
              </Button>
            </div>

            <Alert severity="info">
              This is not a SkyBrush import. The CSV must already use the MDS custom trajectory protocol and be ready
              to execute as-is.
            </Alert>

            {uploadWarnings.length > 0 && (
              <Alert severity="warning">
                {uploadWarnings.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
              </Alert>
            )}
          </Stack>
        </Paper>

        <Paper className="custom-show-card" elevation={0}>
          <div className="custom-show-card__header">
            <Description color="primary" />
            <div>
              <Typography variant="h6">Active Custom CSV</Typography>
              <Typography variant="body2" color="text.secondary">
                Same file on every drone, replayed in each drone&apos;s own local launch frame.
              </Typography>
            </div>
          </div>

          {hasActiveCustomShow ? (
            <>
              <div className="custom-show-page__chip-row">
                <Chip icon={<RuleFolder />} label={customShowInfo.filename} color="primary" variant="outlined" />
                <Chip icon={<Insights />} label={`${customShowInfo.row_count} samples`} variant="outlined" />
                <Chip icon={<FlightTakeoff />} label={formatDuration(customShowInfo.duration_sec)} variant="outlined" />
                <Chip icon={<Route />} label={`${customShowInfo.max_altitude} m max altitude`} variant="outlined" />
              </div>

              <Divider sx={{ my: 2 }} />

              <Stack spacing={1.25}>
                <Typography variant="body2" color="text.secondary">
                  Execution mode: <strong>{customShowInfo.execution_mode || 'local per-drone replay'}</strong>
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  No shared-origin correction, no per-drone file mapping, and no SkyBrush conversion happen in this mode.
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  MDS only validates the protocol, stores it as <code>active.csv</code>, and regenerates the preview.
                </Typography>
              </Stack>
            </>
          ) : (
            <Alert severity="warning">
              No active custom CSV is loaded. Upload a protocol-correct CSV to activate this mode.
            </Alert>
          )}

          {showMissingCsvAlert && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              No active custom CSV is present on the server yet.
            </Alert>
          )}
        </Paper>

        <Paper className="custom-show-card" elevation={0}>
          <div className="custom-show-card__header">
            <RuleFolder color="primary" />
            <div>
              <Typography variant="h6">Protocol Reminder</Typography>
              <Typography variant="body2" color="text.secondary">
                This mode expects a valid MDS custom trajectory file, not a SkyBrush ZIP export.
              </Typography>
            </div>
          </div>

          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">
              Required columns:
            </Typography>
            <div className="custom-show-page__chip-row">
              {requiredColumns.map((column) => (
                <Chip key={column} label={column} size="small" variant="outlined" />
              ))}
            </div>
            <Typography variant="body2" color="text.secondary">
              Every drone executes the same path from wherever it launched, assuming its own local frame is the
              origin. Operators remain responsible for spacing, protocol correctness, and real-world safety checks.
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Read the operational note in{' '}
              <Link href={CUSTOM_SHOW_DOC_URL} target="_blank" rel="noreferrer">
                the Drone Show documentation
              </Link>{' '}
              before using this mode on hardware.
            </Typography>
          </Stack>
        </Paper>

        <Paper className="custom-show-card custom-show-card--preview" elevation={0}>
          <div className="custom-show-card__header">
            <Visibility color="primary" />
            <div>
              <Typography variant="h6">Preview</Typography>
              <Typography variant="body2" color="text.secondary">
                Regenerated from the active custom CSV for a quick operator cross-check.
              </Typography>
            </div>
          </div>

          {previewAvailable && imageSrc && !imageLoadFailed ? (
            <img
              src={imageSrc}
              alt="Custom CSV preview"
              className="custom-show-page__preview-image"
              onError={() => setImageLoadFailed(true)}
              onLoad={() => setImageLoadFailed(false)}
            />
          ) : (
            <Alert severity={hasActiveCustomShow ? 'info' : 'warning'}>
              {hasActiveCustomShow
                ? 'Preview image not available yet. Uploading the CSV again will regenerate it.'
                : 'Upload a valid custom CSV to generate the preview image.'}
            </Alert>
          )}
        </Paper>
      </div>
    </div>
  );
};

export default CustomShowPage;
