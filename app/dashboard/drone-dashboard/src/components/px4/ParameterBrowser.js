import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid } from '@mui/x-data-grid';
import { formatParameterValue, parameterKey, parameterValuesMatch } from '../../utilities/px4ParameterValues';

const differsFromDefault = row => row.default_value != null && !parameterValuesMatch(row.value_type, row.default_value, row.value);

export default function ParameterBrowser({ rows, busy, selectedKey, onInspect, sessionChanges }) {
  const [query, setQuery] = useState(''), [group, setGroup] = useState(''), [filter, setFilter] = useState('all');
  const [compact, setCompact] = useState(false), [expandedGroup, setExpandedGroup] = useState('');
  const host = useRef(null), deferred = useDeferredValue(query);
  useEffect(() => {
    const measure = () => {
      const width = host.current?.getBoundingClientRect().width || window.innerWidth;
      const touch = window.matchMedia?.('(pointer: coarse)').matches || window.navigator.maxTouchPoints > 0;
      setCompact(width < (touch ? 1050 : 760));
    };
    measure();
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    if (host.current) observer?.observe(host.current);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  const groups = useMemo(() => [...new Set(rows.map(row => row.group || row.category || 'Ungrouped'))].sort(), [rows]);
  const visible = useMemo(() => rows.filter(row => {
    if (group && (row.group || row.category || 'Ungrouped') !== group) return false;
    if (filter === 'modified' && !differsFromDefault(row)) return false;
    if (filter === 'session' && !sessionChanges.has(parameterKey(row))) return false;
    if (filter === 'reboot' && row.reboot_required !== true) return false;
    return !deferred.trim() || [row.name, row.short_description, row.long_description, row.unit].filter(Boolean).join(' ').toLowerCase().includes(deferred.trim().toLowerCase());
  }), [rows, group, filter, deferred, sessionChanges]);
  const grouped = useMemo(() => {
    const result = new Map();
    visible.forEach(row => { const name = row.group || row.category || 'Ungrouped'; if (!result.has(name)) result.set(name, []); result.get(name).push(row); });
    return [...result];
  }, [visible]);
  const displayRows = visible.map(row => ({ ...row, id: parameterKey(row), displayValue: `${formatParameterValue(row.value, row)}${row.unit ? ` ${row.unit}` : ''}`,
    signal: [differsFromDefault(row) ? '≠ default' : '', row.reboot_required ? 'Reboot-sensitive' : ''].filter(Boolean).join(' · ') }));
  const columns = [
    { field: 'name', headerName: 'Parameter', minWidth: 190, flex: 1.2, renderCell: ({ row }) => <button type="button" className="px4-row-link" aria-label={`Inspect ${row.name}`} onClick={event => { event.stopPropagation(); onInspect(row); }}>{row.name}</button> },
    { field: 'displayValue', headerName: 'Current', minWidth: 135, flex: .8, align: 'right', headerAlign: 'right' },
    { field: 'group', headerName: 'Group', minWidth: 140, flex: 1 },
    { field: 'signal', headerName: 'Reference', minWidth: 155, flex: 1 },
  ];
  const compactRow = row => <button key={parameterKey(row)} type="button" className={`px4-parameter-row${selectedKey === parameterKey(row) ? ' is-selected' : ''}`}
    aria-label={`Inspect ${row.name}`} onClick={() => onInspect(row)}>
    <span><code>{row.name}</code>{differsFromDefault(row) && <small>≠ default</small>}</span>
    <span><b>{formatParameterValue(row.value, row)}</b>{row.unit && <small>{row.unit}</small>}{row.reboot_required && <small>Reboot-sensitive</small>}</span>
  </button>;
  return <section ref={host} className="px4-browser" aria-label="Parameters">
    <div className="px4-browser-toolbar">
      <label className="px4-search"><span className="px4-visually-hidden">Find parameter</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} aria-label="Find parameter" placeholder="Find parameter" /></label>
      <label><span className="px4-visually-hidden">Parameter group</span><select aria-label="Parameter group" value={group} onChange={event => setGroup(event.target.value)}><option value="">All groups</option>{groups.map(name => <option key={name}>{name}</option>)}</select></label>
      <label><span className="px4-visually-hidden">Parameter filter</span><select aria-label="Parameter filter" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All parameters</option><option value="modified">Different from default</option><option value="session">Changed this session</option><option value="reboot">Reboot-sensitive</option></select></label>
      <span className="px4-browser-count" role="status">{busy ? 'Refreshing…' : `${visible.length} parameters`}</span>
    </div>
    {!visible.length ? <div className="px4-empty">{busy ? 'Reading parameters…' : rows.length ? 'No matching parameters.' : 'Choose an aircraft and fetch its parameters.'}</div>
      : compact ? <div className="px4-parameter-list">{deferred.trim() || group ? visible.map(compactRow) : grouped.map(([name, items]) => <section key={name} className="px4-parameter-group">
        <button type="button" className="px4-group-heading" aria-expanded={expandedGroup === name} onClick={() => setExpandedGroup(expandedGroup === name ? '' : name)}><span>{expandedGroup === name ? '−' : '+'} {name}</span><small>{items.length}</small></button>
        {expandedGroup === name && items.map(compactRow)}
      </section>)}</div>
        : <div className="px4-grid"><DataGrid rows={displayRows} columns={columns} loading={busy} density="compact" rowHeight={44} columnHeaderHeight={40}
          disableColumnMenu disableRowSelectionOnClick rowSelectionModel={selectedKey ? [selectedKey] : []}
          onRowClick={({ row }) => onInspect(row)} pageSizeOptions={[25, 50, 100]}
          initialState={{ pagination: { paginationModel: { pageSize: 50 } } }} sx={{ border: 0, color: 'var(--color-text-primary)' }} /></div>}
  </section>;
}
