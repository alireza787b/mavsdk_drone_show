import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { useAuth } from '../contexts/AuthContext';
import LoginPage from './LoginPage';

jest.mock('../contexts/AuthContext', () => ({ useAuth: jest.fn() }));

const login = jest.fn();

beforeEach(() => {
  login.mockReset();
  useAuth.mockReturnValue({ login, setupRequired: false });
});

function enterCredentials() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'pilot' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'example-password' } });
}

test('reads the form values and blocks repeated submissions while authentication is pending', async () => {
  let failLogin;
  login.mockReturnValueOnce(new Promise((_, reject) => { failLogin = reject; }));
  render(<LoginPage />);

  const username = screen.getByLabelText('Username');
  expect(username).toHaveValue('');
  expect(username).toHaveAttribute('autocomplete', 'username');
  expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password');
  enterCredentials();

  const form = screen.getByRole('form', { name: 'Sign in' });
  fireEvent.submit(form);
  fireEvent.submit(form);

  expect(login).toHaveBeenCalledTimes(1);
  expect(login).toHaveBeenCalledWith({ username: 'pilot', password: 'example-password' });
  expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled();

  failLogin({ response: { status: 401, data: { detail: 'Private validation detail' } } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Check your username and password.');
  expect(screen.queryByText('Private validation detail')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
});

test.each([
  [403, 'Dashboard access was denied. Contact your GCS administrator.'],
  [429, 'Too many sign-in attempts. Wait a moment and try again.'],
  [500, 'Could not sign in. Try again.'],
])('uses a fixed error message for authentication status %s', async (status, message) => {
  login.mockRejectedValueOnce({ response: { status, data: { detail: 'Private validation detail' } } });
  render(<LoginPage />);
  enterCredentials();
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.queryByText('Private validation detail')).not.toBeInTheDocument();
});

test('shows the SSH recovery command and public guide when setup is required', () => {
  useAuth.mockReturnValue({ login, setupRequired: true });
  render(<LoginPage />);

  expect(screen.getByRole('heading', { name: 'Administrator setup required' })).toBeInTheDocument();
  expect(screen.getByText('sudo tools/mds_auth_admin.py add-user admin')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Sign-in help' })).toHaveAttribute(
    'href',
    'https://github.com/alireza787b/mavsdk_drone_show/blob/main/docs/guides/gcs-auth.md#ssh-recovery-cli',
  );
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
});

test('offers recovery when the server reports that setup became required', async () => {
  login.mockRejectedValueOnce({ response: { status: 503, data: { detail: { error: 'setup_required' } } } });
  render(<LoginPage />);
  enterCredentials();
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

  expect(await screen.findByRole('heading', { name: 'Administrator setup required' })).toBeInTheDocument();
  expect(screen.getByText('sudo tools/mds_auth_admin.py add-user admin')).toBeInTheDocument();
});
