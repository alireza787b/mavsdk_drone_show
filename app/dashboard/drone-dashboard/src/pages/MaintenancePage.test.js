import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MaintenancePage from './MaintenancePage';
import useFetch from '../hooks/useFetch';

jest.mock('../hooks/useFetch');
const aircraft = {
  pos_id: 2, hw_id: '41', branch: 'field', in_sync_with_gcs: true,
  git_auth_health_status: 'healthy', repo_access_mode: 'ssh_key',
  // Raw diagnostics can contain local paths. The workspace displays normalized fields.
  git_auth_health_summary: 'check /private/path', env_runtime: { local_env_path: '/private/path' },
};
function open(route) {
  useFetch.mockReturnValue({ data: { git_status: { '41': aircraft, '42': { ...aircraft, hw_id: '42', pos_id: 1 } }, gcs_status: { branch: 'main' } } });
  return render(<MemoryRouter initialEntries={[route]}><MaintenancePage /></MemoryRouter>);
}
test('maintenance exposes working profile routes and scoped repository diagnostics', () => {
  open('/maintenance?hw_id=41');
  expect(screen.getByRole('link', { name: 'Wi-Fi profiles' })).toHaveAttribute('href', '/fleet-ops/wifi');
  expect(screen.getByRole('link', { name: 'MAVLink routing' })).toHaveAttribute('href', '/fleet-ops/mavlink');
  fireEvent.click(screen.getByRole('link', { name: 'Repository access' }));
  expect(screen.getByRole('rowheader', { name: 'P2 · H41' })).toBeInTheDocument();
  expect(screen.queryByText('P1 · H42')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: /align.*H41|alignment for H41/i })).toHaveAttribute('href', '/fleet-ops?hw_id=41');
  expect(screen.queryByText(/private\/path/)).not.toBeInTheDocument();
});
test('a legacy services bookmark retains the chosen hardware ID', () => {
  open('/maintenance?tab=sidecars&hw_id=42');
  expect(screen.getByRole('heading', { name: 'Aircraft services' })).toBeInTheDocument();
  expect(screen.getByRole('rowheader', { name: 'P1 · H42' })).toBeInTheDocument();
});
