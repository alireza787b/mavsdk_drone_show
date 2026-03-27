import React from 'react';
import PropTypes from 'prop-types';
import { FaCheckCircle, FaExclamationTriangle, FaInfoCircle, FaTimesCircle } from 'react-icons/fa';

import { getDroneReadinessModel } from '../utilities/droneReadiness';
import '../styles/DroneReadinessReport.css';

function getStatusIcon(status) {
  if (status === 'ready') {
    return <FaCheckCircle aria-hidden="true" />;
  }
  if (status === 'warning') {
    return <FaInfoCircle aria-hidden="true" />;
  }
  if (status === 'unknown') {
    return <FaInfoCircle aria-hidden="true" />;
  }
  return <FaTimesCircle aria-hidden="true" />;
}

function renderMessageList(messages, emptyLabel) {
  if (!messages.length) {
    return <p className="drone-readiness__empty">{emptyLabel}</p>;
  }

  return (
    <ul className="drone-readiness__list">
      {messages.map((message, index) => (
        <li
          key={`${message.source}-${message.message}-${index}`}
          className={`drone-readiness__list-item ${message.severity || 'warning'}`}
        >
          <span className={`drone-readiness__message-source ${message.source} ${message.severity || 'warning'}`}>
            {message.source}
          </span>
          <span className="drone-readiness__message-text">{message.message}</span>
        </li>
      ))}
    </ul>
  );
}

function getCompactDetailsLabel(readiness) {
  if (readiness.blockers.length === 0 && readiness.warnings.length > 0 && readiness.recentMessages.length === 0) {
    return `${readiness.warnings.length} ${readiness.warnings.length === 1 ? 'advisory' : 'advisories'}`;
  }

  if (readiness.issueCount > 0) {
    return `${readiness.issueCount} active item${readiness.issueCount === 1 ? '' : 's'}`;
  }

  return 'Show readiness details';
}

const DroneReadinessReport = ({ drone = {}, runtimeStatus = null, variant = 'compact' }) => {
  const readiness = getDroneReadinessModel(drone, runtimeStatus);
  const hasCompactDetails = readiness.issueCount > 0 || readiness.recentMessages.length > 0;

  if (variant === 'compact' && readiness.isReady && !hasCompactDetails) {
    return null;
  }

  if (variant === 'detail') {
    return (
      <section className={`drone-readiness drone-readiness--detail ${readiness.status}`}>
        <div className="drone-readiness__header">
          <div className={`drone-readiness__pill ${readiness.status}`}>
            {getStatusIcon(readiness.status)}
            <span>{readiness.statusLabel}</span>
          </div>
          <p className="drone-readiness__summary">{readiness.summary}</p>
        </div>

        <div className="drone-readiness__detail-grid">
          <div className="drone-readiness__section">
            <h4>Blocking Issues</h4>
            {renderMessageList(readiness.blockers, 'No active blocking issues.')}
          </div>
          <div className="drone-readiness__section">
            <h4>Warnings</h4>
            {renderMessageList(readiness.warnings, 'No readiness warnings.')}
          </div>
        </div>

        {readiness.recentMessages.length > 0 && (
          <div className="drone-readiness__section">
            <h4>Recent PX4 Messages</h4>
            {renderMessageList(readiness.recentMessages, 'No recent PX4 status messages.')}
          </div>
        )}

        {readiness.checks.length > 0 && (
          <div className="drone-readiness__section">
            <h4>Readiness Checks</h4>
            <div className="drone-readiness__checks">
              {readiness.checks.map((check) => (
                <div key={check.id} className={`drone-readiness__check ${check.ready ? 'ready' : 'blocked'}`}>
                  <span className="drone-readiness__check-label">{check.label}</span>
                  <span className="drone-readiness__check-state">{check.ready ? 'OK' : 'Attention'}</span>
                  <p className="drone-readiness__check-detail">{check.detail}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    );
  }

  return (
    <div className={`drone-readiness drone-readiness--compact ${readiness.status}`}>
      <div className="drone-readiness__header">
        <div className={`drone-readiness__pill ${readiness.status}`}>
          {getStatusIcon(readiness.status)}
          <span>{readiness.statusLabel}</span>
        </div>
        <p className="drone-readiness__summary">{readiness.summary}</p>
      </div>

      {hasCompactDetails && (
        <details className="drone-readiness__details">
          <summary className="drone-readiness__details-summary">
            <FaExclamationTriangle aria-hidden="true" />
            <span>{getCompactDetailsLabel(readiness)}</span>
          </summary>
          <div className="drone-readiness__details-body">
            <div className="drone-readiness__section">
              <h4>Blocking Issues</h4>
              {renderMessageList(readiness.blockers, 'No active blocking issues.')}
            </div>
            <div className="drone-readiness__section">
              <h4>Warnings</h4>
              {renderMessageList(readiness.warnings, 'No readiness warnings.')}
            </div>
            {readiness.recentMessages.length > 0 && (
              <div className="drone-readiness__section">
                <h4>Recent PX4 Messages</h4>
                {renderMessageList(readiness.recentMessages, 'No recent PX4 status messages.')}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
};

DroneReadinessReport.propTypes = {
  drone: PropTypes.object,
  runtimeStatus: PropTypes.object,
  variant: PropTypes.oneOf(['compact', 'detail']),
};

export default DroneReadinessReport;
