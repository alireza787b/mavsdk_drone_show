import React, { useRef, useState } from 'react';
import { FiArrowRight, FiExternalLink } from 'react-icons/fi';

import mdsMark from '../assets/mds-mark.svg';
import { AircraftSilhouette } from '../components/SwarmAircraftSymbol';
import { useAuth } from '../contexts/AuthContext';
import '../styles/LoginPage.css';

const AUTH_GUIDE_URL = 'https://github.com/alireza787b/mavsdk_drone_show/blob/main/docs/guides/gcs-auth.md#ssh-recovery-cli';

function FormationIllustration() {
  return (
    <div className="login-page__illustration theme-dark" aria-hidden="true">
      <svg viewBox="0 0 600 500" focusable="false">
        <g className="login-page__contours">
          <path d="M-55 315C29 332 83 305 122 254c39-52 49-93 106-129 63-40 164-31 222-68 25-16 45-41 59-79" />
          <path d="M-55 338C43 353 105 327 148 270c36-48 52-93 105-124 63-36 158-29 216-70 34-24 53-54 74-98" />
          <path d="M-55 361C58 378 130 346 175 285c36-48 53-88 104-118 65-37 154-31 212-73 39-28 66-67 84-116" />
          <path d="M-55 385C75 405 157 363 203 300c36-49 57-83 104-110 63-37 153-34 216-81 37-28 67-71 86-122" />
          <path d="M-55 408C90 430 177 384 232 308c33-46 55-72 101-98 60-35 153-35 215-79 43-31 71-76 90-121" />
          <path d="M-55 432C103 458 201 411 261 319c27-40 51-65 99-92 57-32 146-33 212-77 42-28 70-66 89-104" />
          <path d="M-55 456C114 485 232 433 291 335c22-35 45-59 96-87 55-30 140-29 208-74 32-21 58-48 81-83" />
          <path d="M-55 481C129 511 257 459 324 349c18-29 40-54 89-81 56-31 135-29 202-72 24-15 45-34 65-59" />
          <path d="M-55 506C147 538 287 480 354 367c16-27 43-56 84-79 51-29 136-29 197-69 15-10 32-24 49-40" />
          <path d="M157 531c96-21 183-68 227-145 19-33 45-60 80-78 50-26 123-25 196-71" />
        </g>
        <g className="login-page__formation-lines">
          <path d="M183 234l146-57M323 354l44-160M392 147l49-49" />
          <path d="M443 109v-13h-13" />
        </g>
        <g className="login-page__aircraft" transform="translate(174 237) rotate(42) scale(1.45)">
          <AircraftSilhouette />
        </g>
        <g className="login-page__aircraft" transform="translate(319 366) rotate(42) scale(1.45)">
          <AircraftSilhouette />
        </g>
        <g className="login-page__aircraft login-page__aircraft--lead" transform="translate(368 172) rotate(42) scale(2.75)">
          <AircraftSilhouette />
        </g>
      </svg>
    </div>
  );
}

function signInErrorMessage(status) {
  switch (status) {
    case 401:
      return 'Check your username and password.';
    case 403:
      return 'Dashboard access was denied. Contact your GCS administrator.';
    case 429:
      return 'Too many sign-in attempts. Wait a moment and try again.';
    default:
      return 'Could not sign in. Try again.';
  }
}

function LoginPage() {
  const auth = useAuth();
  const inFlight = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [setupRequired, setSetupRequired] = useState(false);
  const showSetup = auth.setupRequired || setupRequired;

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (inFlight.current) return;

    const fields = new FormData(event.currentTarget);
    inFlight.current = true;
    setSubmitting(true);
    setError('');
    try {
      await auth.login({ username: fields.get('username'), password: fields.get('password') });
    } catch (nextError) {
      const response = nextError?.response;
      if (response?.status === 503 && response.data?.detail?.error === 'setup_required') {
        setSetupRequired(true);
      } else {
        setError(signInErrorMessage(response?.status));
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <FormationIllustration />
      <section className="login-page__entry" aria-labelledby="login-title">
        <div className="login-page__brand">
          <img src={mdsMark} alt="" width="36" height="36" />
          <span>MDS Control</span>
        </div>
        <div className="login-page__content">
          <h1 id="login-title" aria-live="polite">{showSetup ? 'Administrator setup required' : 'Sign in'}</h1>
          {showSetup ? (
            <div className="login-page__setup">
              <p>On the ground station, create the first administrator over SSH.</p>
              <code>sudo tools/mds_auth_admin.py add-user admin</code>
            </div>
          ) : (
            <form className="login-page__form" method="post" aria-labelledby="login-title" onSubmit={handleSubmit}>
              <label htmlFor="login-username">Username</label>
              <input
                id="login-username"
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={64}
                required
              />
              <label htmlFor="login-password">Password</label>
              <input
                id="login-password"
                name="password"
                autoComplete="current-password"
                type="password"
                required
              />
              {error && <p className="login-page__error" role="alert">{error}</p>}
              <button type="submit" disabled={submitting}>
                {submitting ? 'Signing in…' : 'Sign in'}
                <FiArrowRight aria-hidden="true" />
              </button>
            </form>
          )}
          <a className="login-page__help" href={AUTH_GUIDE_URL} target="_blank" rel="noreferrer">
            Sign-in help <FiExternalLink aria-hidden="true" />
          </a>
        </div>
      </section>
    </main>
  );
}

export default LoginPage;
