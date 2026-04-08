import React, { useEffect, useState } from 'react';

const FINDING_TYPE_OPTIONS = [
  { value: 'person', label: 'Person' },
  { value: 'vessel', label: 'Vessel' },
  { value: 'vehicle', label: 'Vehicle' },
  { value: 'clue', label: 'Clue' },
  { value: 'hazard', label: 'Hazard' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'anomaly', label: 'Anomaly' },
  { value: 'other', label: 'Other' },
];

const PRIORITY_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
];

const CONFIDENCE_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

const SOURCE_OPTIONS = [
  { value: 'operator_mark', label: 'Operator mark' },
  { value: 'drone_report', label: 'Drone report' },
  { value: 'system_detection', label: 'System detection' },
  { value: 'external_report', label: 'External report' },
];

const STATUS_OPTIONS = [
  { value: 'new', label: 'New' },
  { value: 'under_review', label: 'Under review' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'dismissed', label: 'Dismissed' },
  { value: 'handed_off', label: 'Handed off' },
];

const buildDraft = (finding) => ({
  summary: finding?.summary || '',
  type: finding?.type || 'other',
  priority: finding?.priority || 'medium',
  confidence: finding?.confidence || 'medium',
  source: finding?.source || 'operator_mark',
  status: finding?.status || 'new',
  notes: finding?.notes || '',
});

const FindingReviewPanel = ({
  finding,
  saving,
  deleting,
  onSaveFinding,
  onDeleteFinding,
  onFocusFinding,
  onSeedFollowUpFromFinding,
}) => {
  const [draft, setDraft] = useState(buildDraft(finding));

  useEffect(() => {
    setDraft(buildDraft(finding));
  }, [finding]);

  if (!finding) {
    return (
      <div className="qs-finding-detail qs-finding-detail--empty">
        <div className="qs-empty-copy">
          Select a finding to review, classify, and update operator notes.
        </div>
      </div>
    );
  }

  const handleChange = (key, value) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const handleSave = async () => {
    await onSaveFinding?.(finding.id, draft);
  };

  const handleDelete = async () => {
    await onDeleteFinding?.(finding.id);
  };

  return (
    <div className="qs-finding-detail">
      <div className="qs-finding-detail__header">
        <div>
          <div className="qs-config-title" style={{ marginBottom: 4 }}>Finding Review</div>
          <div className="qs-finding-detail__meta">
            {finding.reported_by_drone ? `Drone ${finding.reported_by_drone}` : 'Operator mark'}
          </div>
        </div>
        <div className="qs-launch-review__chip-row">
          <span className="qs-inline-chip">{finding.type || 'other'}</span>
          <span className="qs-inline-chip">{finding.priority || 'medium'}</span>
        </div>
      </div>

      <div className="qs-finding-form">
        <label className="qs-finding-form__field">
          <span className="qs-config-label">Summary</span>
          <input
            className="qs-config-text-input"
            type="text"
            value={draft.summary}
            onChange={(event) => handleChange('summary', event.target.value)}
            placeholder="Unreviewed observation"
          />
        </label>

        <div className="qs-finding-form__grid">
          <label className="qs-finding-form__field">
            <span className="qs-config-label">Type</span>
            <select
              className="qs-config-select"
              value={draft.type}
              onChange={(event) => handleChange('type', event.target.value)}
            >
              {FINDING_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="qs-finding-form__field">
            <span className="qs-config-label">Priority</span>
            <select
              className="qs-config-select"
              value={draft.priority}
              onChange={(event) => handleChange('priority', event.target.value)}
            >
              {PRIORITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="qs-finding-form__field">
            <span className="qs-config-label">Confidence</span>
            <select
              className="qs-config-select"
              value={draft.confidence}
              onChange={(event) => handleChange('confidence', event.target.value)}
            >
              {CONFIDENCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="qs-finding-form__field">
            <span className="qs-config-label">Status</span>
            <select
              className="qs-config-select"
              value={draft.status}
              onChange={(event) => handleChange('status', event.target.value)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>

        <label className="qs-finding-form__field">
          <span className="qs-config-label">Source</span>
          <select
            className="qs-config-select"
            value={draft.source}
            onChange={(event) => handleChange('source', event.target.value)}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <label className="qs-finding-form__field">
          <span className="qs-config-label">Notes</span>
          <textarea
            className="qs-config-textarea"
            value={draft.notes}
            onChange={(event) => handleChange('notes', event.target.value)}
            placeholder="Add operator notes, contact details, or handoff instructions."
          />
        </label>
      </div>

      <div className="qs-finding-detail__actions">
        <button
          type="button"
          className="qs-btn qs-btn-secondary"
          onClick={() => onFocusFinding?.(finding)}
          disabled={saving || deleting}
        >
          Center Map
        </button>
        <button
          type="button"
          className="qs-btn qs-btn-secondary"
          onClick={() => onSeedFollowUpFromFinding?.(finding)}
          disabled={saving || deleting}
        >
          Follow-up Search
        </button>
        <button
          type="button"
          className="qs-btn qs-btn-primary"
          onClick={handleSave}
          disabled={saving || deleting}
        >
          {saving ? 'Saving…' : 'Save Finding'}
        </button>
        <button
          type="button"
          className="qs-btn qs-btn-danger"
          onClick={handleDelete}
          disabled={saving || deleting}
        >
          {deleting ? 'Removing…' : 'Remove'}
        </button>
      </div>
    </div>
  );
};

export default FindingReviewPanel;
