/**
 * AuthContext.jsx — Global authentication and guest session state.
 *
 * Provides:
 *   - authState: { user, accessToken, workspaceId, isAuthenticated, isGuest, guestToken, guestUsage, guestLimits }
 *   - login(email, password) → void
 *   - signup(email, password, fullName, workspaceName) → void
 *   - beginSocialLogin(provider) → redirects to provider
 *   - completeSocialLogin(provider, code, state, redirectUri) → void
 *   - requestPhoneOtp(phoneNumber) / verifyPhoneOtp(phoneNumber, code) → void
 *   - logout() → void
 *   - initGuestSession() → boolean
 *   - convertGuest(email, password, ...) → void
 *   - refreshToken() → string | null
 *   - apiHeaders() → Headers object with correct auth
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiUrl } from '../lib/apiConfig';
import {
  AUTH_KEYS,
  AUTH_EXPIRED_EVENT,
  AUTH_REFRESHED_EVENT,
  clearSession,
  readApiError,
  refreshAccessToken,
  storeSession,
} from '../lib/authSession';

const AuthContext = createContext(null);

// Refresh tokens are never stored in JS-readable storage: the API keeps them in
// an HttpOnly, SameSite=Strict cookie and lib/authSession.js refreshes through it.
const STORAGE_KEYS = AUTH_KEYS;

// ─────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [accessToken, setAccessToken] = useState(null);
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
    const storedUser = localStorage.getItem(STORAGE_KEYS.USER);
    const storedWs = localStorage.getItem(STORAGE_KEYS.WORKSPACE_ID);
    const storedGuestToken = sessionStorage.getItem(STORAGE_KEYS.GUEST_TOKEN);
    const storedGuestId = sessionStorage.getItem(STORAGE_KEYS.GUEST_SESSION_ID);

    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
        setWorkspaceId(storedWs);
        if (storedToken) {
          setAccessToken(storedToken);
        } else {
          // Access token missing: restore the session from the refresh cookie.
          refreshAccessToken().finally(() => setLoading(false));
          return;
        }
      } catch {
        clearSession();
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
    if (!accessToken) return;
    // Refresh 2 minutes before the 15-minute expiry window (via the HttpOnly cookie).
    const delay = (13 * 60 * 1000);
    refreshTimerRef.current = setTimeout(() => {
      refreshAccessToken();
    }, delay);
    return () => clearTimeout(refreshTimerRef.current);
  }, [accessToken]);

  // ── Keep React state in sync with refreshes done anywhere (other tabs, API retries) ──
  useEffect(() => {
    const onRefreshed = (event) => {
      const data = event.detail || {};
      setAccessToken(data.access_token);
      if (data.workspace_id) setWorkspaceId(data.workspace_id);
      if (data.user) setUser(data.user);
    };
    const onExpired = () => {
      setUser(null);
      setAccessToken(null);
      setWorkspaceId(null);
    };
    const onStorage = (event) => {
      if (event.key !== STORAGE_KEYS.ACCESS_TOKEN) return;
      if (event.newValue) setAccessToken(event.newValue);
      else onExpired();
    };
    window.addEventListener(AUTH_REFRESHED_EVENT, onRefreshed);
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(AUTH_REFRESHED_EVENT, onRefreshed);
      window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

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
      const res = await fetch(apiUrl('/guest/session'), {
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
      return true;
    }

    try {
      const res = await fetch(apiUrl('/guest/session'), {
        method: 'POST',
        // Short timeout — don't block UI if backend is down
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return false; // Silently skip if backend does not have guest routes yet
      const data = await res.json();
      setGuestToken(data.guest_token);
      setGuestSessionId(data.guest_session_id);
      setGuestUsage(data.usage);
      setGuestLimits(data.limits);
      sessionStorage.setItem(STORAGE_KEYS.GUEST_TOKEN, data.guest_token);
      sessionStorage.setItem(STORAGE_KEYS.GUEST_SESSION_ID, data.guest_session_id);
      return true;
    } catch {
      // Backend offline or guest routes not available — silently ignore
      // App still works in degraded mode without guest tracking
      return false;
    }
  }, []);  // Remove addToast dependency — no toast on failure

  const updateGuestUsage = useCallback((action) => {
    setGuestUsage(prev => ({ ...prev, [`${action}_count`]: (prev[`${action}_count`] || 0) + 1 }));
  }, []);

  // ── Auth Flows ──────────────────────────────────────────────
  const _storeAuthData = (data) => {
    // The refresh token in `data` is ignored on purpose: the HttpOnly cookie set
    // by the same response is the only copy the browser keeps.
    const userData = storeSession(data);
    setUser(userData);
    setAccessToken(data.access_token);
    setWorkspaceId(data.workspace_id);
    // Clear guest data
    sessionStorage.removeItem(STORAGE_KEYS.GUEST_TOKEN);
    sessionStorage.removeItem(STORAGE_KEYS.GUEST_SESSION_ID);
    setGuestToken(null);
    setGuestSessionId(null);
  };

  const login = useCallback(async (email, password) => {
    const res = await fetch(apiUrl('/auth/login'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Login failed'));
    const data = await res.json();
    _storeAuthData(data);
    addToast(`Welcome back, ${email}!`, 'success');
    return data;
  }, [addToast]);

  const signup = useCallback(async (email, password, fullName, workspaceName) => {
    const res = await fetch(apiUrl('/auth/signup'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, full_name: fullName, workspace_name: workspaceName }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Signup failed'));
    const data = await res.json();
    return data;
  }, []);

  const beginSocialLogin = useCallback(async (provider = 'google') => {
    const normalizedProvider = provider.toLowerCase();
    const redirectUri = `${window.location.origin}/auth/oauth/${normalizedProvider}/callback`;
    const res = await fetch(apiUrl(`/auth/oauth/${normalizedProvider}/start`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ redirect_uri: redirectUri, next_path: '/app/analyze' }),
    });
    if (!res.ok) throw new Error(await readApiError(res, `${provider} sign-in is not available`));
    const data = await res.json();
    window.location.assign(data.authorization_url);
    return data;
  }, []);

  const completeSocialLogin = useCallback(async (provider, code, state, redirectUri) => {
    const normalizedProvider = provider.toLowerCase();
    const res = await fetch(apiUrl(`/auth/oauth/${normalizedProvider}/callback`), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, state, redirect_uri: redirectUri }),
    });
    if (!res.ok) throw new Error(await readApiError(res, `${provider} sign-in failed`));
    const data = await res.json();
    _storeAuthData(data);
    addToast(`Signed in with ${provider}.`, 'success');
    return data;
  }, [addToast]);

  const requestPhoneOtp = useCallback(async (phoneNumber) => {
    const res = await fetch(apiUrl('/auth/otp/request'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_number: phoneNumber }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Could not send OTP'));
    const data = await res.json();
    return data;
  }, []);

  const verifyPhoneOtp = useCallback(async (phoneNumber, code, workspaceName = null) => {
    const res = await fetch(apiUrl('/auth/otp/verify'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_number: phoneNumber, code, workspace_name: workspaceName }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'OTP verification failed'));
    const data = await res.json();
    _storeAuthData(data);
    addToast('Signed in with phone OTP.', 'success');
    return data;
  }, [addToast]);

  const convertGuest = useCallback(async (email, password, fullName, workspaceName, preserveData = true) => {
    const res = await fetch(apiUrl('/guest/convert'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-Guest-Token': guestToken },
      body: JSON.stringify({ email, password, full_name: fullName, workspace_name: workspaceName, preserve_data: preserveData }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Conversion failed'));
    const data = await res.json();
    _storeAuthData(data);
    addToast('Account created! Your guest data has been saved. ✨', 'success', 8000);
    return data;
  }, [guestToken, addToast]);

  const logout = useCallback(async () => {
    try {
      await fetch(apiUrl('/auth/logout'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch {}
    setUser(null);
    setAccessToken(null);
    setWorkspaceId(null);
    clearSession();
    addToast('You have been logged out.', 'info');
  }, [addToast]);

  const silentRefresh = useCallback(() => refreshAccessToken(), []);

  const forgotPassword = useCallback(async (email) => {
    const res = await fetch(apiUrl('/auth/forgot-password'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Failed'));
    const data = await res.json();
    return data;
  }, []);

  const resetPassword = useCallback(async (token, newPassword) => {
    const res = await fetch(apiUrl('/auth/reset-password'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Reset failed'));
    const data = await res.json();
    return data;
  }, []);

  const verifyEmail = useCallback(async (token) => {
    const res = await fetch(apiUrl('/auth/verify-email'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) throw new Error(await readApiError(res, 'Verification failed'));
    const data = await res.json();
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
    beginSocialLogin,
    completeSocialLogin,
    requestPhoneOtp,
    verifyPhoneOtp,
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
