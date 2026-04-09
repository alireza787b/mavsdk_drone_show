import React from 'react';
import PropTypes from 'prop-types';

const renderValueSummary = (value) => {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  return String(value);
};

const Px4ParamProfilePanel = ({
  profile,
  loading = false,
  compareTargetLabel = '',
  compareResult = null,
  compareLoading = false,
  onPreviewDiff = () => {},
  onUseInBatch = () => {},
  onExportProfile = () => {},
}) => {
  if (loading) {
    return (
      <section className="px4-panel px4-profile-panel">
        <div className="px4-profile-panel__empty">Loading profile…</div>
      </section>
    );
  }

  if (!profile) {
    return (
      <section className="px4-panel px4-profile-panel">
        <div className="px4-profile-panel__empty">Select a repo profile to review its parameters and target guidance.</div>
      </section>
    );
  }

  const differenceCount = compareResult?.total_changed || 0;

  return (
    <section className="px4-panel px4-profile-panel">
      <div className="px4-panel__header">
        <div>
          <h2>{profile.name}</h2>
          <span>{profile.entries.length} parameter row(s)</span>
        </div>
        <div className="px4-param-inspector__chips">
          <span className="px4-param-chip">{profile.recommended_scope}</span>
          {(profile.tags || []).map((tag) => (
            <span key={tag} className="px4-param-chip">{tag}</span>
          ))}
        </div>
      </div>

      {profile.description ? (
        <p className="px4-profile-panel__summary">{profile.description}</p>
      ) : null}

      <div className="px4-profile-panel__actions">
        <button type="button" className="primary" onClick={onUseInBatch}>
          Use in Batch
        </button>
        <button type="button" onClick={onPreviewDiff} disabled={!compareTargetLabel || compareLoading}>
          {compareLoading ? 'Comparing…' : `Preview vs ${compareTargetLabel || 'selected drone'}`}
        </button>
        <button type="button" onClick={onExportProfile}>
          Export JSON
        </button>
      </div>

      {compareResult ? (
        <div className="px4-import-preview">
          <div className="px4-import-preview__header">
            <div>
              <strong>{compareTargetLabel || 'Selected drone'} diff preview</strong>
              <span>{differenceCount} changed row(s)</span>
            </div>
          </div>
          <div className="px4-import-preview__list">
            {(compareResult.differences || []).slice(0, 8).map((difference) => (
              <div key={`${difference.component_id}:${difference.name}`} className="px4-import-preview__row">
                <strong>{difference.name}</strong>
                <span>
                  {renderValueSummary(difference.current_value)} → {renderValueSummary(difference.desired_value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="px4-profile-panel__entries">
        {(profile.entries || []).map((entry) => (
          <div key={`${entry.component_id}:${entry.name}`} className="px4-profile-panel__entry">
            <div>
              <strong>{entry.name}</strong>
              <span>{entry.value_type.toUpperCase()}</span>
            </div>
            <code>{renderValueSummary(entry.value)}</code>
          </div>
        ))}
      </div>
    </section>
  );
};

Px4ParamProfilePanel.propTypes = {
  profile: PropTypes.shape({
    profile_id: PropTypes.string.isRequired,
    name: PropTypes.string.isRequired,
    description: PropTypes.string,
    recommended_scope: PropTypes.string,
    tags: PropTypes.arrayOf(PropTypes.string),
    entries: PropTypes.arrayOf(PropTypes.shape({
      component_id: PropTypes.number.isRequired,
      name: PropTypes.string.isRequired,
      value_type: PropTypes.string.isRequired,
      value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    })),
  }),
  loading: PropTypes.bool,
  compareTargetLabel: PropTypes.string,
  compareResult: PropTypes.shape({
    total_changed: PropTypes.number,
    differences: PropTypes.arrayOf(PropTypes.shape({
      component_id: PropTypes.number.isRequired,
      name: PropTypes.string.isRequired,
      current_value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
      desired_value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    })),
  }),
  compareLoading: PropTypes.bool,
  onPreviewDiff: PropTypes.func,
  onUseInBatch: PropTypes.func,
  onExportProfile: PropTypes.func,
};

export default Px4ParamProfilePanel;
