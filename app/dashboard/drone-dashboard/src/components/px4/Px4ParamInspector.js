import React from 'react';
import PropTypes from 'prop-types';

const trimTrailingZeros = (value) => String(value)
  .replace(/(\.\d*?[1-9])0+$/, '$1')
  .replace(/\.0+$/, '')
  .replace(/^-0$/, '0');

const formatParameterValue = (value, row) => {
  if (value === null || value === undefined || value === '') {
    return '—';
  }

  if (typeof value === 'number' && Number.isFinite(value)) {
    if (row?.value_type === 'int') {
      return String(Math.trunc(value));
    }

    if (row?.value_type === 'float') {
      const decimalPlaces = Number.isFinite(Number(row?.decimal_places))
        ? Math.min(Math.max(Number(row.decimal_places), 0), 6)
        : null;

      if (decimalPlaces !== null) {
        return trimTrailingZeros(value.toFixed(decimalPlaces));
      }

      return trimTrailingZeros(value.toFixed(4));
    }
  }

  return String(value);
};

const formatParameterRange = (row) => {
  const hasMin = row?.min_value !== null && row?.min_value !== undefined;
  const hasMax = row?.max_value !== null && row?.max_value !== undefined;

  if (!hasMin && !hasMax) {
    return '—';
  }

  if (hasMin && hasMax) {
    return `${formatParameterValue(row.min_value, row)} – ${formatParameterValue(row.max_value, row)}`;
  }

  if (hasMin) {
    return `≥ ${formatParameterValue(row.min_value, row)}`;
  }

  return `≤ ${formatParameterValue(row.max_value, row)}`;
};

const Px4ParamInspector = ({
  row,
  draftValue,
  onDraftValueChange,
  onResetToCurrent,
  onResetToDefault,
  onSave,
  saving = false,
  writeBlockedReason = '',
}) => {
  if (!row) {
    return (
      <aside className="px4-param-inspector px4-param-inspector--empty">
        <div className="px4-param-inspector__empty">
          <strong>Select a parameter</strong>
          <p>Choose a row to review its value, limits, defaults, and edit controls.</p>
        </div>
      </aside>
    );
  }

  const inputType = row.value_type === 'custom' ? 'text' : 'number';
  const inputStep = row.value_type === 'int' ? '1' : 'any';
  const saveDisabled = saving || Boolean(writeBlockedReason);
  const hasDefault = row.default_value !== null && row.default_value !== undefined;

  return (
    <aside className="px4-param-inspector">
      <header className="px4-param-inspector__header">
        <div>
          <h3>{row.name}</h3>
          <div className="px4-param-inspector__chips">
            <span className="px4-param-chip">{row.value_type.toUpperCase()}</span>
            {row.reboot_required ? <span className="px4-param-chip px4-param-chip--warning">Reboot</span> : null}
            {row.unit ? <span className="px4-param-chip">{row.unit}</span> : null}
            {row.group ? <span className="px4-param-chip">{row.group}</span> : null}
          </div>
        </div>
        {row.docs_url ? (
          <a href={row.docs_url} target="_blank" rel="noopener noreferrer" className="px4-param-link">
            PX4 Docs
          </a>
        ) : null}
      </header>

      {row.short_description ? (
        <p className="px4-param-inspector__summary">{row.short_description}</p>
      ) : null}
      {row.long_description ? (
        <p className="px4-param-inspector__detail">{row.long_description}</p>
      ) : null}

      <div className="px4-param-inspector__grid">
        <div>
          <span>Current</span>
          <strong>{formatParameterValue(row.value, row)}</strong>
        </div>
        <div>
          <span>Default</span>
          <strong>{formatParameterValue(row.default_value, row)}</strong>
        </div>
        <div>
          <span>Range</span>
          <strong>{formatParameterRange(row)}</strong>
        </div>
        <div>
          <span>Restart</span>
          <strong>
            {row.reboot_required === null || row.reboot_required === undefined
              ? 'Not declared'
              : (row.reboot_required ? 'Required' : 'Not required')}
          </strong>
        </div>
      </div>

      <label className="px4-param-inspector__field">
        <span>New Value</span>
        <input
          type={inputType}
          step={inputStep}
          value={draftValue}
          onChange={(event) => onDraftValueChange(event.target.value)}
          aria-label={`Set ${row.name} value`}
        />
      </label>

      <div className="px4-param-inspector__actions">
        <button type="button" onClick={onResetToCurrent}>
          Reset to Current
        </button>
        <button type="button" onClick={onResetToDefault} disabled={!hasDefault}>
          Use Default
        </button>
        <button type="button" className="primary" onClick={onSave} disabled={saveDisabled}>
          {saving ? 'Saving…' : 'Save Parameter'}
        </button>
      </div>

      {writeBlockedReason ? (
        <div className="px4-param-inspector__notice px4-param-inspector__notice--warning">
          {writeBlockedReason}
        </div>
      ) : null}
    </aside>
  );
};

Px4ParamInspector.propTypes = {
  row: PropTypes.shape({
    name: PropTypes.string.isRequired,
    value_type: PropTypes.string.isRequired,
    value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    default_value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    min_value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    max_value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    unit: PropTypes.string,
    reboot_required: PropTypes.bool,
    short_description: PropTypes.string,
    long_description: PropTypes.string,
    docs_url: PropTypes.string,
    group: PropTypes.string,
    category: PropTypes.string,
  }),
  draftValue: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onDraftValueChange: PropTypes.func.isRequired,
  onResetToCurrent: PropTypes.func.isRequired,
  onResetToDefault: PropTypes.func.isRequired,
  onSave: PropTypes.func.isRequired,
  saving: PropTypes.bool,
  writeBlockedReason: PropTypes.string,
};

export default Px4ParamInspector;
