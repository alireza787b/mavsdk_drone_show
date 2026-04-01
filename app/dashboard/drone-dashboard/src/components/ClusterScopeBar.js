import React from 'react';
import PropTypes from 'prop-types';
import '../styles/ClusterScopeBar.css';

const ClusterScopeBar = ({
  label = 'Scope',
  options = [],
  selectedId = 'all',
  onSelect,
  summary = '',
}) => {
  if (!Array.isArray(options) || options.length === 0) {
    return null;
  }

  return (
    <section className="cluster-scope-bar" aria-label={label}>
      <div className="cluster-scope-bar__header">
        <div>
          <strong>{label}</strong>
          {summary && <span>{summary}</span>}
        </div>
      </div>

      <div className="cluster-scope-bar__rail" role="list" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`cluster-scope-bar__chip ${String(selectedId) === String(option.id) ? 'active' : ''}`}
            onClick={() => onSelect(option.id)}
            title={[
              option.label,
              option.count !== undefined ? `(${option.count})` : '',
              option.description || '',
            ].filter(Boolean).join(' ')}
            aria-pressed={String(selectedId) === String(option.id)}
          >
            <span className="cluster-scope-bar__chip-label">
              {option.label}
              {option.count !== undefined ? ` (${option.count})` : ''}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
};

ClusterScopeBar.propTypes = {
  label: PropTypes.string,
  options: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    label: PropTypes.string.isRequired,
    description: PropTypes.string,
    count: PropTypes.number,
  })),
  selectedId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onSelect: PropTypes.func.isRequired,
  summary: PropTypes.string,
};

export default ClusterScopeBar;
