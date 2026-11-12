import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { DataGrid } from '@mui/x-data-grid';
import ParameterBrowser from './ParameterBrowser';

// Characterize the browser/grid contract, not MUI's rendering performance.
// Actual virtualization/geometry is checked in the built browser on the test host.
jest.mock('@mui/x-data-grid', () => ({ DataGrid: jest.fn() }));
const renderGrid = props => <div data-testid="grid" data-row-count={props.rows.length} data-page-size={props.paginationModel.pageSize}>
  {!props.hideFooter && <><select aria-label="Rows per page" value={props.paginationModel.pageSize} onChange={event => props.onPaginationModelChange({ page: 0, pageSize: Number(event.target.value) })}>
    {props.pageSizeOptions.map(item => <option key={item.value ?? item} value={item.value ?? item}>{item.label ?? item}</option>)}
  </select><button onClick={() => props.onPaginationModelChange({ ...props.paginationModel, page: 2 })}>Next test page</button></>}
  <button onClick={() => props.onSortModelChange([{ field: 'name', sort: 'desc' }])}>Sort test rows</button>
  {props.rows.slice(0, 8).map((row, index) => <div key={row.id} className={props.getRowClassName({ row, indexRelativeToCurrentPage: index })}>
    {props.columns[0].renderCell({ row, tabIndex: index === 0 ? 0 : -1 })}
  </div>)}
</div>;

const rows = Array.from({ length: 2049 }, (_, index) => ({ component_id: 1, name: `TEST_${index}`, value_type: 'int', value: index,
  group: index === 2048 ? undefined : 'Position control', category: index === 2048 ? 'Sensors' : 'Velocity', default_value: 0 }));
const props = { rows, busy: false, selectedKey: '', onInspect: jest.fn(), sessionChanges: new Set(), aircraftId: '1' };
const gridProps = () => DataGrid.mock.calls[DataGrid.mock.calls.length - 1][0];

beforeEach(() => { jest.clearAllMocks(); DataGrid.mockImplementation(renderGrid); window.innerWidth = 1440; });

test('List starts at 50; Show all uses the documented sentinel without disabling virtualization', () => {
  render(<ParameterBrowser {...props} />);
  expect(screen.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(gridProps().paginationModel).toEqual({ page: 0, pageSize: 50 });
  fireEvent.change(screen.getByRole('combobox', { name: 'Rows per page' }), { target: { value: '-1' } });
  expect(gridProps().paginationModel).toEqual({ page: 0, pageSize: -1 });
  expect(gridProps().rows).toHaveLength(2049);
  expect(gridProps().disableVirtualization).toBeUndefined();
  expect(gridProps().autoHeight).toBeUndefined();
  expect(gridProps().rowSelection).toBe(false);
});

test('Groups flatten only expanded children into the same virtualized grid and never inspect headers', () => {
  render(<ParameterBrowser {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Sort test rows' }));
  fireEvent.click(screen.getByRole('button', { name: 'Groups', exact: true }));
  expect(gridProps().rows).toHaveLength(2);
  expect(gridProps().columns[0].colSpan('Position control', gridProps().rows[0])).toBe(4);
  expect(gridProps().columns[0].colSpan('TEST_0', rows[0])).toBe(1);
  expect(gridProps().sortModel).toEqual([]);
  expect(gridProps().hideFooter).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Position control · 2048 parameters' }));
  expect(gridProps().rows).toHaveLength(2050);
  expect(gridProps().paginationModel.pageSize).toBe(-1);
  expect(gridProps().disableVirtualization).toBeUndefined();
  expect(props.onInspect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect TEST_0' }));
  expect(props.onInspect).toHaveBeenCalledWith(expect.objectContaining({ name: 'TEST_0', component_id: 1 }));
  fireEvent.click(screen.getByRole('button', { name: 'Position control · 2048 parameters' }));
  expect(gridProps().rows).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'List', exact: true }));
  expect(gridProps().sortModel).toEqual([{ field: 'name', sort: 'desc' }]);
});

test('search includes group and category, reveals collapsed matches, and restores expansion after clearing', () => {
  render(<ParameterBrowser {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Groups', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Position control · 2048 parameters' }));
  const search = screen.getByRole('searchbox', { name: 'Find parameter' });
  fireEvent.change(search, { target: { value: 'Sensors' } });
  expect(gridProps().rows.map(row => row.name)).toEqual(['TEST_2048']);
  fireEvent.change(search, { target: { value: 'Velocity' } });
  expect(gridProps().rows).toHaveLength(2048);
  expect(gridProps().rows.every(row => !row.isGroup)).toBe(true);
  fireEvent.change(search, { target: { value: '' } });
  expect(gridProps().rows).toHaveLength(2050);
  expect(screen.getByRole('button', { name: 'Position control · 2048 parameters' })).toHaveAttribute('aria-expanded', 'true');
});

test('compact All and expanded groups use DataGrid; resize keeps view, filter and inspection', () => {
  window.innerWidth = 390;
  render(<ParameterBrowser {...props} selectedKey="1:TEST_1" />);
  fireEvent.change(screen.getByRole('combobox', { name: 'Rows per page' }), { target: { value: '-1' } });
  expect(gridProps().columns).toHaveLength(2);
  expect(gridProps().columns[0].colSpan('Group', { isGroup: true })).toBe(2);
  expect(gridProps().rows).toHaveLength(2049);
  expect(gridProps().getRowClassName({ row: gridProps().rows[1], indexRelativeToCurrentPage: 1 })).toContain('is-inspected');
  fireEvent.click(screen.getByRole('button', { name: 'Groups', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Position control · 2048 parameters' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Parameter filter' }), { target: { value: 'modified' } });
  window.innerWidth = 1440;
  fireEvent(window, new Event('resize'));
  expect(gridProps().columns).toHaveLength(4);
  expect(screen.getByRole('button', { name: 'Groups', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('combobox', { name: 'Parameter filter' })).toHaveValue('modified');
  expect(screen.getByRole('button', { name: 'Position control · 2047 parameters' })).toHaveAttribute('aria-expanded', 'true');
  expect(gridProps().disableVirtualization).toBeUndefined();
});

test('custom cell buttons follow the grid tab sequence and filtering resets pagination', () => {
  render(<ParameterBrowser {...props} />);
  expect(screen.getByRole('button', { name: 'Inspect TEST_0' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByRole('button', { name: 'Inspect TEST_1' })).toHaveAttribute('tabindex', '-1');
  fireEvent.click(screen.getByRole('button', { name: 'Next test page' }));
  expect(gridProps().paginationModel.page).toBe(2);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Find parameter' }), { target: { value: 'TEST_2048' } });
  expect(gridProps().paginationModel.page).toBe(0);
});

test('no match can be cleared without changing inspected identity', () => {
  render(<ParameterBrowser {...props} />);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Find parameter' }), { target: { value: 'not-found' } });
  expect(screen.getByText('No matching parameters.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(gridProps().rows).toHaveLength(2049);
  expect(props.onInspect).not.toHaveBeenCalled();
});
