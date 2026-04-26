// src/pages/ManageDroneShow.js
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ToastContainer } from 'react-toastify';
import { FaCheckCircle, FaFileArchive, FaRocket, FaRoute, FaUpload } from 'react-icons/fa';

import ExportSection from '../components/ExportSection';
import ImportSection from '../components/ImportSection';
import VisualizationSection from '../components/VisualizationSection';
import {
  ActionIconButton,
  MetricStrip,
  OperatorCard,
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import '../styles/ManageDroneShow.css';

const WORKFLOW_STEPS = [
  {
    key: 'create',
    label: 'Create',
    detail: 'Blender / SkyBrush',
    icon: <FaFileArchive />,
  },
  {
    key: 'upload',
    label: 'Upload',
    detail: 'ZIP pipeline',
    icon: <FaUpload />,
    active: true,
  },
  {
    key: 'config',
    label: 'Config',
    detail: 'Mission geometry',
    route: '/mission-config',
    icon: <FaRoute />,
  },
  {
    key: 'launch',
    label: 'Launch',
    detail: 'Overview preflight',
    route: '/mission-control',
    icon: <FaRocket />,
  },
];

const WorkflowGuidanceSection = () => {
  const navigate = useNavigate();

  return (
    <OperatorNotice
      tone="info"
      title="Standard SkyBrush ZIP workflow"
      className="manage-drone-show__workflow"
      action={(
        <ActionIconButton
          icon={<FaFileArchive />}
          label="Open Custom CSV mode"
          size="sm"
          onClick={() => navigate('/custom-show')}
        >
          Custom CSV
        </ActionIconButton>
      )}
    >
      <div className="manage-drone-show__workflow-body">
        <div className="manage-drone-show__workflow-steps" aria-label="Drone show import workflow">
          {WORKFLOW_STEPS.map((step) => (
            <button
              key={step.key}
              type="button"
              className={[
                'manage-drone-show__workflow-step',
                step.active ? 'is-active' : '',
              ].filter(Boolean).join(' ')}
              disabled={!step.route}
              onClick={() => step.route && navigate(step.route)}
              aria-current={step.active ? 'step' : undefined}
            >
              <span aria-hidden="true">{step.icon}</span>
              <strong>{step.label}</strong>
              <small>{step.detail}</small>
            </button>
          ))}
        </div>
      </div>
    </OperatorNotice>
  );
};

const ManageDroneShow = () => {
  const [uploadCount, setUploadCount] = useState(0);

  const statusItems = [
    {
      key: 'pipeline',
      label: 'Pipeline',
      value: 'SkyBrush ZIP',
      detail: 'normal show import',
      icon: <FaFileArchive />,
      tone: 'info',
    },
    {
      key: 'state',
      label: 'Current Step',
      value: 'Upload',
      detail: 'process and inspect',
      icon: <FaCheckCircle />,
      tone: 'success',
    },
  ];

  return (
    <PageShell
      className="manage-drone-show-container"
      eyebrow="Drone show authoring"
      title="Manage Drone Show"
      subtitle="Import, inspect, export."
      docsRoute="/manage-drone-show"
      status={<StatusBadge tone="info">ZIP pipeline</StatusBadge>}
    >
      <ToastContainer />

      <MetricStrip items={statusItems} label="Drone show import status" />

      <WorkflowGuidanceSection />

      <OperatorCard className="manage-drone-show__section">
        <ImportSection setUploadCount={setUploadCount} />
      </OperatorCard>

      <OperatorCard className="manage-drone-show__section">
        <VisualizationSection uploadCount={uploadCount} />
      </OperatorCard>

      <OperatorCard className="manage-drone-show__section">
        <ExportSection />
      </OperatorCard>
    </PageShell>
  );
};

export default ManageDroneShow;
