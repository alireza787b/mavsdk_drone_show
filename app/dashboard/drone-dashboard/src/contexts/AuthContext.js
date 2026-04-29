import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import {
  getAuthStatusResponse,
  loginResponse,
  logoutResponse,
  setGcsCsrfToken,
} from '../services/gcsApiService';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getAuthStatusResponse();
      setStatus(response.data || {});
      if (response.data?.csrf_token) {
        setGcsCsrfToken(response.data.csrf_token);
      }
      return response.data || {};
    } catch (nextError) {
      setError(nextError);
      throw nextError;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => {
      setLoading(false);
    });
  }, [refresh]);

  const login = useCallback(async ({ username, password }) => {
    setError(null);
    const response = await loginResponse({ username, password });
    const nextStatus = await refresh();
    return response.data || nextStatus;
  }, [refresh]);

  const logout = useCallback(async () => {
    setError(null);
    await logoutResponse();
    await refresh();
  }, [refresh]);

  const value = useMemo(() => {
    const dashboardAuthEnabled = Boolean(status?.dashboard_auth_enabled);
    const authenticated = dashboardAuthEnabled ? Boolean(status?.authenticated) : true;
    return {
      status: status || {},
      loading,
      error,
      dashboardAuthEnabled,
      apiAuthEnabled: Boolean(status?.api_auth_enabled),
      setupRequired: Boolean(status?.setup_required),
      authenticated,
      user: status?.user || null,
      role: status?.role || status?.user?.role || null,
      refresh,
      login,
      logout,
    };
  }, [error, loading, login, logout, refresh, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return value;
}
