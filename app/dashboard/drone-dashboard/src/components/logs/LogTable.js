import React, { useEffect, useRef, useState } from 'react';
import { DataGrid, useGridApiRef } from '@mui/x-data-grid';
import LogRowDetail from './LogRowDetail';
import { recordTime } from '../../features/log-workspace/logWorkspace';

export default function LogTable({ entries, autoScroll = false, sourceLabel, identity, emptyStateTitle = 'No matching records', loading = false }) {
  const [inspected, setInspected] = useState(null), [compact, setCompact] = useState(false);
  const host = useRef(null), grid = useGridApiRef();
  useEffect(() => { setInspected(null); }, [identity]);
  useEffect(() => {
    const measure = () => setCompact((host.current?.getBoundingClientRect().width || window.innerWidth) < 720);
    measure(); const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    if (host.current) observer?.observe(host.current);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  useEffect(() => {
    if (autoScroll && entries.length) grid.current?.scrollToIndexes?.({ rowIndex: entries.length - 1 });
  }, [entries, autoScroll, grid]);
  const inspect = entry => setInspected({ ...entry });
  const columns = [
    { field: 'ts', headerName: 'Time UTC', width: 192, renderCell: ({ value }) => <span className="logs-time">{recordTime(value)}</span> },
    { field: 'level', headerName: 'Severity', width: 104, renderCell: ({ value }) => <span className={`logs-severity is-${String(value).toLowerCase()}`}>{value || 'Unknown'}</span> },
    { field: 'component', headerName: 'Component', width: 145 },
    { field: 'msg', headerName: 'Message', minWidth: 230, flex: 1, renderCell: ({ row }) => <button type="button" className="logs-row-button" aria-label={`Inspect record ${row.msg}`} onClick={event => { event.stopPropagation(); inspect(row); }}>{row.msg}</button> },
  ];
  return <section ref={host} className="logs-list" aria-label="Log records">
    {!entries.length ? <p className="logs-empty" role="status">{loading ? 'Loading records…' : emptyStateTitle}</p>
      : compact ? <div className="logs-compact-list">{entries.map(entry => <button key={entry._id} type="button" className="logs-compact-row" onClick={() => inspect(entry)} aria-label={`Inspect record ${entry.msg}`}>
        <span><time>{recordTime(entry.ts)}</time><strong className={`logs-severity is-${String(entry.level).toLowerCase()}`}>{entry.level || 'Unknown'}</strong></span><small>{entry.component || 'Unknown component'}</small><span className="logs-row-message">{entry.msg}</span>
      </button>)}</div> : <div className="logs-grid"><DataGrid apiRef={grid} rows={entries} getRowId={row => row._id} columns={columns} loading={loading}
        density="compact" rowHeight={44} columnHeaderHeight={40} disableColumnMenu disableRowSelectionOnClick onRowClick={({ row }) => inspect(row)}
        pageSizeOptions={[100]} initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}
        sx={{ border: 0, color: 'var(--color-text-primary)' }} /></div>}
    {inspected && <LogRowDetail key={inspected._id} entry={inspected} sourceLabel={sourceLabel} onClose={() => setInspected(null)} />}
  </section>;
}
