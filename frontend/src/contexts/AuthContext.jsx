/**
 * AuthContext.jsx — Global authentication and guest session state.
 *
 * Provides:
 *   - authState: { user, accessToken, workspaceId, isAuthenticated, isGuest, guestToken, guestUsage, guestLimits }
 *   - login(email, password) → void
 *   - signup(email, password, fullName, workspaceName) → void
 *   - logout() → void
 *   - initGuestSession() → void
 *   - convertGuest(email, password, ...) → void
 *   - refreshToken() → string | null
 *   - apiHeaders() → Headers object with correct auth
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

const AuthContext = createContext(null);

const STORAGE_KEYS = {
  ACCESS_TOKEN: 'dp_access_token',
  REFRESH_TOKEN: 'dp_refresh_token',
  USER: 'dp_user',
  WORKSPACE_ID: 'dp_workspace_id',
  GUEST_TOKEN: 'dp_guest_token',
  GUEST_SESSION_ID: 'dp_guest_session_id',
};

// ─────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [accessToken, setAccessToken] = useState(null);
  const [refreshTokenVal, setRefreshTokenVal] = useState(null);
  const [workspaceId, setWorkspaceId] = useState(null);
  const [guestToken, setGuestToken] = useState(null);
  const [guestSessionId, setGuestSessionId] = useState(null);
  const [guestUsage, setGuestUsage] = useState({ upload_count: 0, query_count: 0, report_count: 0, export_count: 0 });
  const [guestLimits, setGuestLimits] = useState({ upload_count: 5, query_count: 20, report_count: 1, export_count: 3, max_file_size_bytes: 5242880 });
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState([]);
  const refreshTimerRef = useRef(null);

  // ── Toast helper ────────────────────────────────────────────
  const addToast = useCallback((message, type = 'info', duration = 5000) => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // ── Hydrate from storage on mount ──────────────────────────
  useEffect(() => {
    const storedToken = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
    const storedRefresh = localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
    const storedUser = localStorage.getItem(STORAGE_KEYS.USER);
    const storedWs = localStorage.getItem(STORAGE_KEYS.WORKSPACE_ID);
    const storedGuestToken = sessionStorage.getItem(STORAGE_KEYS.GUEST_TOKEN);
    const storedGuestId = sessionStorage.getItem(STORAGE_KEYS.GUEST_SESSION_ID);

    if (storedToken && storedUser) {
      try {
        setUser(JSON.parse(storedUser));
        setAccessToken(storedToken);
        setRefreshTokenVal(storedRefresh);
        setWorkspaceId(storedWs);
      } catch {
        localStorage.clear();
      }
    } else if (storedGuestToken) {
      setGuestToken(storedGuestToken);
      setGuestSessionId(storedGuestId);
      // Refresh guest usage info
      fetchGuestInfo(storedGuestToken);
    }
    setLoading(false);
  }, []);

  // ── Auto-refresh access token before expiry ─────────────────
  useEffect(() => {
    if (!refreshTokenVal) return;
    // Refresh 2 minutes before the 15-minute expiry window
    const delay = (13 * 60 * 1000);
    refreshTimerRef.current = setTimeout(() => {
      silentRefresh();
    }, delay);
    return () => clearTimeout(refreshTimerRef.current);
  }, [refreshTokenVal]);

  // ── API Headers helper ──────────────────────────────────────
  const apiHeaders = useCallback((extraHeaders = {}) => {
    const headers = { 'Content-Type': 'application/json', ...extraHeaders };
    if (accessToken) {
      headers['Authorization'] = `Bearer ${accessToken}`;
    }
    if (workspaceId) {
      headers['X-Workspace-ID'] = workspaceId;
    }
    if (guestToken && !accessToken) {
      headers['X-Guest-Token'] = guestToken;
    }
    return headers;
  }, [accessToken, workspaceId, guestToken]);

  // ── Guest Session ───────────────────────────────────────────
  const fetchGuestInfo = async (token) => {
    try {
      const res = await fetch(`${API_BASE}/guest/session`, {
        headers: { 'X-Guest-Token': token },
      });
      if (res.ok) {
        const data = await res.json();
        setGuestUsage(data.usage);
        setGuestLimits(data.limits);
      }
    } catch {}
  };

  const initGuestSession = useCallback(async () => {
    // If already have a valid guest session, refresh its info
    const existing = sessionStorage.getItem(STORAGE_KEYS.GUEST_TOKEN);
    if (existing) {
      setGuestToken(existing);
      setGuestSessionId(sessionStorage.getItem(STORAGE_KEYS.GUEST_SESSION_ID));
      // Silently refresh info — ignore failures
      fetchGuestInfo(existing).catch(() => {});
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/guest/session`, {
        method: 'POST',
        // Short timeout — don't block UI if backend is down
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return; // Silently skip — backend may not have guest routes yet
      const data = await res.json();
      setGuestToken(data.guest_token);
      setGuestSessionId(data.guest_session_id);
      setGuestUsage(data.usage);
      setGuestLimits(data.limits);
      sessionStorage.setItem(STORAGE_KEYS.GUEST_TOKEN, data.guest_token);
      sessionStorage.setItem(STORAGE_KEYS.GUEST_SESSION_ID, data.guest_session_id);
    } catch {
      // Backend offline or guest routes not available — silently ignore
      // App still works in degraded mode without guest tracking
    }
  }, []);  // Remove addToast dependency — no toast on failure

  const updateGuestUsage = useCallback((action) => {
    setGuestUsage(prev => ({ ...prev, [`${action}_count`]: (prev[`${action}_count`] || 0) + 1 }));
  }, []);

  // ── Auth Flows ──────────────────────────────────────────────
  const _storeAuthData = (data) => {
    const userData = { user_id: data.user_id, email: data.email };
    setUser(userData);
    setAccessToken(data.access_token);
    setRefreshTokenVal(data.refresh_token);
    setWorkspaceId(data.workspace_id);
    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, data.access_token);
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, data.refresh_token);
    localStorage.setItem(STORAGE_KEYS.USER, JSON.stringify(userData));
    localStorage.setItem(STORAGE_KEYS.WORKSPACE_ID, data.workspace_id);
    // Clear guest data
    sessionStorage.removeItem(STORAGE_KEYS.GUEST_TOKEN);
    sessionStorage.removeItem(STORAGE_KEYS.GUEST_SESSION_ID);
    setGuestToken(null);
    setGuestSessionId(null);
  };

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');
    _storeAuthData(data);
    addToast(`Welcome back, ${email}!`, 'success');
    return data;
  }, [addToast]);

  const signup = useCallback(async (email, password, fullName, workspaceName) => {
    const res = await fetch(`${API_BASE}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, full_name: fullName, workspace_name: workspaceName }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Signup failed');
    return data;
  }, []);

  const convertGuest = useCallback(async (email, password, fullName, workspaceName, preserveData = true) => {
    const res = await fetch(`${API_BASE}/guest/convert`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Guest-Token': guestToken },
      body: JSON.stringify({ email, password, full_name: fullName, workspace_name: workspaceName, preserve_data: preserveData }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Conversion failed');
    _storeAuthData(data);
    addToast('Account created! Your guest data has been saved. ✨', 'success', 8000);
    return data;
  }, [guestToken, addToast]);

  const logout = useCallback(async () => {
    if (refreshTokenVal) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${accessToken}` },
          body: JSON.stringify({ refresh_token: refreshTokenVal }),
        });
      } catch {}
    }
    setUser(null);
    setAccessToken(null);
    setRefreshTokenVal(null);
    setWorkspaceId(null);
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN);
    localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN);
    localStorage.removeItem(STORAGE_KEYS.USER);
    localStorage.removeItem(STORAGE_KEYS.WORKSPACE_ID);
    addToast('You have been logged out.', 'info');
  }, [refreshTokenVal, accessToken, addToast]);

  const silentRefresh = useCallback(async () => {
    const stored = localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
    if (!stored) return null;
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: stored }),
      });
      if (!res.ok) { logout(); return null; }
      const data = await res.json();
      setAccessToken(data.access_token);
      setRefreshTokenVal(data.refresh_token);
      setWorkspaceId(data.workspace_id);
      localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, data.access_token);
      localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, data.refresh_token);
      localStorage.setItem(STORAGE_KEYS.WORKSPACE_ID, data.workspace_id);
      return data.access_token;
    } catch {
      return null;
    }
  }, [logout]);

  const forgotPassword = useCallback(async (email) => {
    const res = await fetch(`${API_BASE}/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed');
    return data;
  }, []);

  const resetPassword = useCallback(async (token, newPassword) => {
    const res = await fetch(`${API_BASE}/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Reset failed');
    return data;
  }, []);

  const verifyEmail = useCallback(async (token) => {
    const res = await fetch(`${API_BASE}/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Verification failed');
    return data;
  }, []);

  const value = {
    user,
    accessToken,
    workspaceId,
    isAuthenticated: !!user && !!accessToken,
    isGuest: !!guestToken && !user,
    guestToken,
    guestSessionId,
    guestUsage,
    guestLimits,
    loading,
    toasts,
    // Actions
    login,
    signup,
    logout,
    convertGuest,
    initGuestSession,
    updateGuestUsage,
    forgotPassword,
    resetPassword,
    verifyEmail,
    silentRefresh,
    apiHeaders,
    addToast,
    dismissToast,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}

export default AuthContext;
