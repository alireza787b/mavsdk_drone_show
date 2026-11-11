import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { toast } from 'react-toastify';
import CustomShowWorkspace from './CustomShowWorkspace';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { importCustomShowResponse, postGcsResource } from '../services/gcsApiService';
jest.mock('../hooks/useGcsResourcePolling');
jest.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }));
jest.mock('react-toastify', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock('../components/CustomShowOperate', () => () => <input aria-label="Persistent operation state" defaultValue="Reviewed targets" />);
jest.mock('../services/gcsApiService', () => ({ ...jest.requireActual('../services/gcsApiService'), importCustomShowResponse: jest.fn(), postGcsResource: jest.fn() }));
const metadata = { exists: true, filename: 'active.csv', sha256: 'test-revision', row_count: 120,
  duration_sec: 70, max_altitude: 8, preview_exists: true, preview_themes: { light: true, dark: true } };
const mount = route => render(<MemoryRouter initialEntries={[route || '/custom-show']}><CustomShowWorkspace runtimeMode="sitl" /></MemoryRouter>);
beforeEach(() => { jest.clearAllMocks(); useGcsResourcePolling.mockReturnValue({ data: metadata }); });
test('setup uses the actual dark variant and tabs retain operation state', () => {
  mount();
  fireEvent.change(screen.getByLabelText('Persistent operation state'), { target: { value: 'Deliberate selection' } });
  fireEvent.click(screen.getByRole('tab', { name: 'Design / Setup' }));
  expect(screen.getByRole('img')).toHaveAttribute('src', expect.stringContaining('theme=dark'));
  expect(screen.getByText('1:10')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Operate' }));
  expect(screen.getByLabelText('Persistent operation state')).toHaveValue('Deliberate selection');
});
test('invalid replacement clears the prior pending file, and loading never launches', async () => {
  mount('/custom-show?tab=setup');
  const input = screen.getByLabelText('CSV file');
  fireEvent.change(input, { target: { files: [new File(['csv'], 'valid.csv')] } });
  expect(screen.getByRole('button', { name: 'Validate & load' })).toBeEnabled();
  fireEvent.change(input, { target: { files: [new File(['wrong'], 'wrong.zip')] } });
  expect(screen.getByRole('button', { name: 'Validate & load' })).toBeDisabled();
  expect(toast.error).toHaveBeenCalledWith('Choose a CSV file.');
  importCustomShowResponse.mockResolvedValue({ data: { success: true, warnings: ['Source replaced'] } });
  fireEvent.change(input, { target: { files: [new File(['csv'], 'valid.csv')] } });
  fireEvent.click(screen.getByRole('button', { name: 'Validate & load' }));
  await waitFor(() => expect(importCustomShowResponse).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByText('Source replaced')).toBeInTheDocument());
  expect(postGcsResource).not.toHaveBeenCalled();
});
test('legacy light-only preview offers explicit refresh, not a white fallback', async () => {
  useGcsResourcePolling.mockReturnValue({ data: { ...metadata, preview_themes: { light: true, dark: false } } });
  postGcsResource.mockResolvedValue({ data: { success: true } });
  mount('/custom-show?tab=setup');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh preview' }));
  await waitFor(() => expect(postGcsResource).toHaveBeenCalledTimes(1));
  expect(importCustomShowResponse).not.toHaveBeenCalled();
});
