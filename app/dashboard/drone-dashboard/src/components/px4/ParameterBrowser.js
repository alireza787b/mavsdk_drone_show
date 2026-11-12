import React, { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid } from '@mui/x-data-grid';
import { formatParameterValue, parameterKey, parameterValuesMatch } from '../../utilities/px4ParameterValues';

const differsFromDefault = row => row.default_value != null && !parameterValuesMatch(row.value_type, row.default_value, row.value);
const groupName = row => row.group || row.category || 'Ungrouped';
const PAGE_SIZES = [25, 50, 100, { value: -1, label: 'Show all' }];

export default function ParameterBrowser({ rows, busy, selectedKey, onInspect, sessionChanges, aircraftId = '', readError = '', onRefresh }) {
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all'), [view, setView] = useState('list');
  const [compact, setCompact] = useState(false), [expandedGroups, setExpandedGroups] = useState(() => new Set());
  const [pagination, setPagination] = useState({ page: 0, pageSize: 50 });
  const [sortModel, setSortModel] = useState([]);
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
  const visible = useMemo(() => rows.filter(row => {
    if (filter === 'modified' && !differsFromDefault(row)) return false;
    if (filter === 'session' && !sessionChanges.has(parameterKey(row))) return false;
    if (filter === 'reboot' && row.reboot_required !== true) return false;
    return !deferred.trim() || [row.name, row.group, row.category, row.short_description, row.long_description, row.unit].filter(Boolean).join(' ').toLowerCase().includes(deferred.trim().toLowerCase());
  }), [rows, filter, deferred, sessionChanges]);
  // Group headings and children share the same virtualized surface at every
  // width. Never render a second, unbounded mobile list for Show all or search.
  const grouped = view === 'groups' && !deferred.trim();
  const displayRows = useMemo(() => {
    const leaves = visible.map(row => ({ ...row, id: parameterKey(row), group: groupName(row),
      displayValue: `${formatParameterValue(row.value, row)}${row.unit ? ` ${row.unit}` : ''}`,
      signal: [differsFromDefault(row) ? '≠ default' : '', row.reboot_required ? 'Reboot-sensitive' : ''].filter(Boolean).join(' · ') }));
    if (!grouped) return leaves;
    const groups = new Map();
    leaves.forEach(row => { if (!groups.has(row.group)) groups.set(row.group, []); groups.get(row.group).push(row); });
    return [...groups].sort(([left], [right]) => left.localeCompare(right)).flatMap(([name, items]) => [
      { id: `group:${name}`, name, isGroup: true, count: items.length }, ...(expandedGroups.has(name) ? items : []),
    ]);
  }, [visible, grouped, expandedGroups]);
  useEffect(() => { setPagination(previous => ({ ...previous, page: 0 })); }, [deferred, filter, view, aircraftId]);
  const toggleGroup = useCallback(name => setExpandedGroups(previous => {
    const next = new Set(previous); if (next.has(name)) next.delete(name); else next.add(name); return next;
  }), []);
  const inspect = row => { if (row.isGroup) toggleGroup(row.name); else onInspect(row); };
  const columns = useMemo(() => [
    { field: 'name', headerName: 'Parameter', minWidth: compact ? 175 : 190, flex: compact ? 1.3 : 1.2,
      sortable: !grouped, colSpan: (_value, row) => row?.isGroup ? compact ? 2 : 4 : 1,
      renderCell: ({ row, tabIndex }) => row.isGroup
        ? <button type="button" className="px4-group-heading" tabIndex={tabIndex} aria-expanded={expandedGroups.has(row.name)} aria-label={`${row.name} · ${row.count} parameters`}
          onClick={event => { event.stopPropagation(); toggleGroup(row.name); }}><span aria-hidden="true">{expandedGroups.has(row.name) ? '▾' : '▸'}</span><span>{row.name}</span><small>{row.count}</small></button>
        : <button type="button" className="px4-row-link" tabIndex={tabIndex} aria-label={`Inspect ${row.name}`} onClick={event => { event.stopPropagation(); onInspect(row); }}>
          <span>{row.name}</span>{compact && row.signal && <small>{row.signal}</small>}</button> },
    { field: 'displayValue', headerName: 'Snapshot value', minWidth: compact ? 115 : 135, flex: .8, align: 'right', headerAlign: 'right', sortable: !grouped },
    ...(!compact ? [{ field: 'group', headerName: 'Group', minWidth: 140, flex: 1, sortable: !grouped },
      { field: 'signal', headerName: 'Reference', minWidth: 155, flex: 1, sortable: !grouped }] : []),
  ], [compact, grouped, expandedGroups, onInspect, toggleGroup]);
  const emptyMessage = busy ? 'Reading parameters…' : !aircraftId ? 'Choose an aircraft to read its parameters.'
    : readError && !rows.length ? 'Parameters could not be read. Retry the snapshot read.'
      : rows.length ? 'No matching parameters.' : 'No parameters in this aircraft snapshot.';
  return <section ref={host} className="px4-browser" aria-label="Parameters">
    <div className="px4-browser-toolbar">
      <label className="px4-search"><span className="px4-visually-hidden">Find parameter</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} aria-label="Find parameter" placeholder="Find parameter or group" /></label>
      <div className="px4-browser-views" role="group" aria-label="Parameter view">{['list', 'groups'].map(mode => <button type="button" key={mode} className="operator-button operator-button--ghost" aria-pressed={view === mode} onClick={() => setView(mode)}>{mode === 'list' ? 'List' : 'Groups'}</button>)}</div>
      <label><span className="px4-visually-hidden">Parameter filter</span><select aria-label="Parameter filter" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All parameters</option><option value="modified">Different from default</option><option value="session">Changed this session</option><option value="reboot">Reboot-sensitive</option></select></label>
      <span className="px4-browser-count" role="status">{busy ? 'Refreshing…' : `${visible.length} parameter${visible.length === 1 ? '' : 's'}`}{view === 'groups' && deferred.trim() ? ' · Search results' : ''}</span>
    </div>
    {!visible.length ? <div className="px4-empty" role="status"><p>{emptyMessage}</p>
      {!busy && readError && aircraftId && !rows.length && <button type="button" className="operator-button operator-button--ghost" onClick={onRefresh}>Retry read</button>}
      {!busy && rows.length > 0 && <button type="button" className="operator-button operator-button--ghost" onClick={() => { setQuery(''); setFilter('all'); }}>Clear filters</button>}
    </div> : <div className={`px4-grid${compact ? ' px4-grid--compact' : ''}`}><DataGrid rows={displayRows} columns={columns} loading={busy}
      density={compact ? 'standard' : 'compact'} rowHeight={compact ? 58 : 44} columnHeaderHeight={40}
      disableColumnMenu disableRowSelectionOnClick rowSelection={false} hideFooter={grouped}
      getRowClassName={({ row, indexRelativeToCurrentPage }) => row.isGroup ? 'px4-grid-group' : `${indexRelativeToCurrentPage % 2 ? 'px4-grid-row--odd' : 'px4-grid-row--even'}${selectedKey === row.id ? ' is-inspected' : ''}`}
      onRowClick={({ row }) => inspect(row)} pageSizeOptions={PAGE_SIZES}
      paginationModel={grouped ? { page: 0, pageSize: -1 } : pagination} onPaginationModelChange={model => { if (!grouped) setPagination(model); }}
      sortModel={grouped ? [] : sortModel} onSortModelChange={model => { if (!grouped) setSortModel(model); }}
      sx={{ border: 0, color: 'var(--color-text-primary)' }} /></div>}
  </section>;
}
