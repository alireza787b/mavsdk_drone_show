// src/components/logs/LogRowDetail.js
import React, { useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { FaTimes } from 'react-icons/fa';

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
};

const formatTimestamp = (value) => {
  if (!value) {
    return '-';
  }
  try {
    return new Date(value).toISOString();
  } catch {
    return String(value);
  }
};

const DetailChip = ({ label, value }) => (
  <div className="log-row-detail-chip">
    <span>{label}</span>
    <strong>{formatValue(value)}</strong>
  </div>
);

const LogRowDetail = ({ entry, onClose }) => {
  const titleId = useId();

  useEffect(() => {
    if (!entry) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose?.();
      }
    };

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleEscape);
    };
  }, [entry, onClose]);

  if (!entry) return null;

  const content = (
    <div
      className="log-row-detail"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose?.();
        }
      }}
    >
      <section
        className={`log-row-detail__panel level-${entry.level || 'INFO'}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="log-row-detail__header">
          <div>
            <span className="log-row-detail__eyebrow">Log entry</span>
            <h2 id={titleId}>{entry.level || 'INFO'} · {entry.component || 'system'}</h2>
          </div>
          <button
            type="button"
            className="log-row-detail__close"
            onClick={onClose}
            aria-label="Close log detail"
          >
            <FaTimes aria-hidden="true" />
          </button>
        </header>

        <div className="log-row-detail__meta" aria-label="Log metadata">
          <DetailChip label="Time" value={formatTimestamp(entry.ts)} />
          <DetailChip label="Source" value={entry.source} />
          <DetailChip label="Drone" value={entry.drone_id != null ? `#${entry.drone_id}` : 'GCS'} />
          <DetailChip label="Level" value={entry.level || 'INFO'} />
        </div>

        <div className="log-row-detail__message">
          <span>Message</span>
          <p>{entry.msg || '-'}</p>
        </div>

        {entry.extra ? (
          <div className="log-row-detail__json">
            <span>Extra</span>
            <pre>{JSON.stringify(entry.extra, null, 2)}</pre>
          </div>
        ) : null}

        <details className="log-row-detail__raw">
          <summary>Raw entry</summary>
          <pre>{JSON.stringify(entry, null, 2)}</pre>
        </details>
      </section>
    </div>
  );

  if (typeof document === 'undefined') {
    return content;
  }

  return createPortal(content, document.body);
};

export default LogRowDetail;
