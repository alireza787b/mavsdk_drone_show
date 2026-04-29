import React, { useState } from 'react';
import { FaLock, FaSignInAlt } from 'react-icons/fa';

import { buildDocsUrl } from '../config/routeDocs';
import { useAuth } from '../contexts/AuthContext';
import { GIT_BRANCH, GIT_REPO } from '../version';
import '../styles/LoginPage.css';

const AUTH_GUIDE_URL = buildDocsUrl(
  { docPath: 'docs/guides/gcs-auth.md' },
  { repoUrl: GIT_REPO, branch: GIT_BRANCH },
);

function LoginPage() {
  const auth = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await auth.login({ username, password });
    } catch (nextError) {
      const detail = nextError?.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : detail?.message || nextError?.response?.data?.message || 'Login failed. Check username and password.';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  if (auth.setupRequired) {
    return (
      <main className="login-page">
        <section className="login-card login-card--wide">
          <FaLock className="login-card__mark" aria-hidden="true" />
          <p className="login-card__eyebrow">Setup required</p>
          <h1>MDS auth needs an admin user</h1>
          <p>
            Auth is enabled, but no admin user exists. SSH to the GCS and run:
          </p>
          <code>sudo tools/mds_auth_admin.py add-user admin</code>
          <a href={AUTH_GUIDE_URL} target="_blank" rel="noreferrer">Open auth recovery guide</a>
        </section>
      </main>
    );
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <FaLock className="login-card__mark" aria-hidden="true" />
        <p className="login-card__eyebrow">MDS secure dashboard</p>
        <h1>Operator login</h1>
        <label>
          <span>Username</span>
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Password</span>
          <input
            autoComplete="current-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="login-card__error" role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          <FaSignInAlt aria-hidden="true" />
          {submitting ? 'Checking' : 'Enter dashboard'}
        </button>
      </form>
    </main>
  );
}

export default LoginPage;
