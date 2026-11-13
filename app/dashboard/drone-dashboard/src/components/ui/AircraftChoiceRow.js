import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/AircraftChoiceRow.css';

/** Controlled identity choice only. No discovery, dispatch or shared selection. */
export default function AircraftChoiceRow({ id, name, detail = '', checked, disabled = false, onChange,
  status = null, className = '', label = `Include ${name} (H${id})` }) {
  return <label className={`aircraft-choice-row ${checked ? 'is-included' : ''} ${className}`.trim()}>
    <input type="checkbox" checked={checked} disabled={disabled} aria-label={label}
      onChange={event => onChange(event.target.checked)} />
    <strong>{name}{detail && <small>{detail}</small>}</strong>
    {status && <span className="aircraft-choice-row__status">{status}</span>}
  </label>;
}
AircraftChoiceRow.propTypes = { id: PropTypes.string.isRequired, name: PropTypes.string.isRequired,
  detail: PropTypes.string, checked: PropTypes.bool.isRequired, disabled: PropTypes.bool,
  onChange: PropTypes.func.isRequired, status: PropTypes.node, className: PropTypes.string, label: PropTypes.string };
