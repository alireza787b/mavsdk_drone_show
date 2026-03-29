import React from 'react';
import PropTypes from 'prop-types';

import '../../styles/TrajectoryPolicyNotes.css';

const TrajectoryPolicyNotes = ({ notes = [], title = 'Operator policy', className = '' }) => {
  if (!notes.length) {
    return null;
  }

  return (
    <section className={`trajectory-policy-notes ${className}`.trim()} aria-label={title}>
      <div className="trajectory-policy-notes__header">
        <strong>{title}</strong>
        <span>Shared execution doctrine for planner, processing, and launch review.</span>
      </div>
      <div className="trajectory-policy-notes__grid">
        {notes.map((note) => (
          <div key={note.key || note.label} className="trajectory-policy-notes__item">
            <span className="trajectory-policy-notes__label">{note.label}</span>
            <span className="trajectory-policy-notes__detail">{note.detail}</span>
          </div>
        ))}
      </div>
    </section>
  );
};

TrajectoryPolicyNotes.propTypes = {
  notes: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string,
      label: PropTypes.string.isRequired,
      detail: PropTypes.string.isRequired,
    })
  ),
  title: PropTypes.string,
  className: PropTypes.string,
};

export default TrajectoryPolicyNotes;
