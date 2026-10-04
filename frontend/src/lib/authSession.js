/**
 * authSession.js — browser session handling shared by every API call.
 *
 * - Both tokens live ONLY in HttpOnly, SameSite=Strict cookies set by the API
 *   (`dp_access`, 15 min; `dp_refresh`, 7 days).  JavaScript never sees them, so
 *   an injected script cannot exfiltrate a session.
 * - Unsafe requests echo the readable `dp_csrf` cookie in `X-CSRF-Token`
 *   (double-submit CSRF protection; a cross-site page can do neither).
 * - Only non-secret profile data (`dp_user`, `dp_workspace_id`) is kept in
 *   localStorage so the UI knows a session exists.
 * - `authedFetch` refreshes once through the cookie and retries when the API
 *   answers 401.  Refreshes are de-duplicated inside a tab (shared promise) and
 *   across tabs (Web Locks + a session epoch), because refresh tokens rotate.
 */
import { apiUrl } from './apiConfig.js'

export const AUTH_KEYS = {
  LEGACY_ACCESS_TOKEN: 'dp_access_token',
  LEGACY_REFRESH_TOKEN: 'dp_refresh_token',
  USER: 'dp_user',
  WORKSPACE_ID: 'dp_workspace_id',
  SESSION_EPOCH: 'dp_session_epoch',
  GUEST_TOKEN: 'dp_guest_token',
  GUEST_SESSION_ID: 'dp_guest_session_id',
}

export const AUTH_REFRESHED_EVENT = 'dp-auth-refreshed'
export const AUTH_EXPIRED_EVENT = 'dp-auth-expired'
export const CSRF_COOKIE = 'dp_csrf'
export const SESSION_MODE_HEADERS = { 'X-Session-Mode': 'cookie' }

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const hasWindow = () => typeof window !== 'undefined'

function safeGet(storage, key) {
  try { return storage?.getItem(key) ?? null } catch { return null }
}

function safeSet(storage, key, value) {
  try {
    if (value === null || value === undefined) storage?.removeItem(key)
    else storage?.setItem(key, value)
  } catch { /* storage unavailable (private mode) */ }
}

/** Remove bearer tokens persisted by older builds (sessions now live in HttpOnly cookies). */
export function takeLegacyTokens() {
  if (!hasWindow()) return { refresh: null }
  const refresh = safeGet(window.sessionStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN)
    || safeGet(window.localStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN)
  safeSet(window.sessionStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN, null)
  safeSet(window.localStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN, null)
  safeSet(window.localStorage, AUTH_KEYS.LEGACY_ACCESS_TOKEN, null)
  return { refresh }
}

export function getCsrfToken() {
  if (!hasWindow() || typeof document === 'undefined') return null
  const match = (document.cookie || '').match(/(?:^|;\s*)dp_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

export function getStoredUser() {
  if (!hasWindow()) return null
  try { return JSON.parse(safeGet(window.localStorage, AUTH_KEYS.USER) || 'null') } catch { return null }
}

/** True while this browser believes it has a signed-in session (cookies decide for real). */
export function hasSession() {
  return !!getStoredUser()
}

export function getWorkspaceId() {
  return hasWindow() ? safeGet(window.localStorage, AUTH_KEYS.WORKSPACE_ID) : null
}

export function getGuestToken() {
  return hasWindow() ? safeGet(window.sessionStorage, AUTH_KEYS.GUEST_TOKEN) : null
}

function sessionEpoch() {
  return hasWindow() ? safeGet(window.localStorage, AUTH_KEYS.SESSION_EPOCH) : null
}

/** Persist the non-secret profile from an auth response; tokens are never stored. */
export function storeSession(data) {
  if (!hasWindow()) return null
  const user = {
    user_id: data.user_id,
    email: data.email,
    full_name: data.full_name || null,
    phone_number: data.phone_number || null,
  }
  safeSet(window.localStorage, AUTH_KEYS.USER, JSON.stringify(user))
  if (data.workspace_id) safeSet(window.localStorage, AUTH_KEYS.WORKSPACE_ID, data.workspace_id)
  safeSet(window.localStorage, AUTH_KEYS.SESSION_EPOCH, String(Date.now()))
  takeLegacyTokens()
  return user
}

export function clearSession() {
  if (!hasWindow()) return
  safeSet(window.localStorage, AUTH_KEYS.USER, null)
  safeSet(window.localStorage, AUTH_KEYS.WORKSPACE_ID, null)
  safeSet(window.localStorage, AUTH_KEYS.SESSION_EPOCH, null)
  takeLegacyTokens()
}

/** Headers for a credentialed request: CSRF for unsafe methods, workspace / guest context. */
export function sessionHeaders(method = 'GET', extra = {}) {
  const headers = { ...extra }
  if (!SAFE_METHODS.has(String(method).toUpperCase())) {
    const csrf = getCsrfToken()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  if (hasSession()) {
    const workspaceId = getWorkspaceId()
    if (workspaceId) headers['X-Workspace-ID'] = workspaceId
  } else {
    const guestToken = getGuestToken()
    if (guestToken) headers['X-Guest-Token'] = guestToken
  }
  return headers
}

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms))

async function requestRefresh() {
  const { refresh: legacy } = takeLegacyTokens()
  const body = { workspace_id: getWorkspaceId() }
  if (legacy) body.refresh_token = legacy

  for (let attempt = 0; attempt < 3; attempt += 1) {
    let resp
    try {
      resp = await fetch(apiUrl('/auth/refresh'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...sessionHeaders('POST', SESSION_MODE_HEADERS) },
        body: JSON.stringify(body),
      })
    } catch {
      return { ok: false, transient: true }
    }
    if (resp.ok) {
      const data = await resp.json()
      return { ok: true, data }
    }
    // 409 = another tab/request rotated the cookie a moment ago; the cookie we
    // will send next time is already the new one.
    if (resp.status === 409) {
      await sleep(300 * (attempt + 1))
      delete body.refresh_token
      continue
    }
    if (resp.status >= 500 || resp.status === 429) return { ok: false, transient: true }
    return { ok: false, transient: false }
  }
  return { ok: false, transient: true }
}

let inflight = null

/**
 * Refresh the session cookies.  Resolves true on success; false when the
 * session is gone (an AUTH_EXPIRED_EVENT is dispatched) or the API is
 * temporarily unreachable.
 */
export function refreshSession() {
  if (inflight) return inflight
  const startedEpoch = sessionEpoch()

  const run = async () => {
    // Another tab may have refreshed while this one waited for the lock.
    const current = sessionEpoch()
    if (current && current !== startedEpoch) return true

    const result = await requestRefresh()
    if (result.ok) {
      const user = storeSession(result.data)
      if (hasWindow()) {
        window.dispatchEvent(new CustomEvent(AUTH_REFRESHED_EVENT, {
          detail: { user, workspace_id: result.data.workspace_id },
        }))
      }
      return true
    }
    if (!result.transient) {
      clearSession()
      if (hasWindow()) window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
    return false
  }

  inflight = (async () => {
    try {
      if (hasWindow() && window.navigator?.locks?.request) {
        return await window.navigator.locks.request('dp-auth-refresh', run)
      }
      return await run()
    } finally {
      inflight = null
    }
  })()
  return inflight
}

/** fetch() against the API with the session cookies, CSRF header and one refresh-and-retry on 401. */
export async function authedFetch(path, options = {}) {
  const { headers: extraHeaders, ...rest } = options
  const method = rest.method || 'GET'
  const send = () => fetch(apiUrl(path), {
    credentials: 'include',
    ...rest,
    headers: sessionHeaders(method, extraHeaders),
  })
  const resp = await send()
  if (resp.status !== 401 || !hasSession()) return resp

  const refreshed = await refreshSession()
  if (!refreshed) return resp
  return send()
}

/** Extract a human-readable message from any API error response (JSON or not). */
export async function readApiError(resp, fallback = 'Request failed') {
  let text = ''
  try { text = await resp.text() } catch { return fallback }
  if (!text) return `${fallback} (HTTP ${resp.status})`
  try {
    const data = JSON.parse(text)
    const detail = data?.detail
    return (
      (typeof data?.error === 'string' && data.error)
      || (typeof data?.message === 'string' && data.message)
      || (typeof detail === 'string' && detail)
      || (detail && typeof detail.message === 'string' && detail.message)
      || `${fallback} (HTTP ${resp.status})`
    )
  } catch {
    // Proxy/HTML error pages (413 from nginx, 502/504 gateway errors, …)
    if (resp.status === 413) return 'File is too large to upload.'
    if (resp.status === 502 || resp.status === 503 || resp.status === 504) {
      return 'The server is temporarily unavailable. Please try again.'
    }
    return `${fallback} (HTTP ${resp.status})`
  }
}

/**
 * Poll a durable background job until it finishes.
 * Resolves with the job object (status "succeeded"); rejects with an Error
 * carrying the job's error message on failure or timeout.
 */
export async function waitForJob(jobId, { timeoutMs = 10 * 60 * 1000, onProgress, signal } = {}) {
  const deadline = Date.now() + timeoutMs
  let delay = 750
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error('Cancelled')
    const resp = await authedFetch(`/jobs/${encodeURIComponent(jobId)}`, { signal })
    if (!resp.ok) throw new Error(await readApiError(resp, 'Could not check job status'))
    const job = await resp.json()
    if (job.status === 'succeeded') return job
    if (job.status === 'failed' || job.status === 'cancelled') {
      throw new Error(job.error || 'Background processing failed')
    }
    onProgress?.(job)
    await sleep(delay)
    delay = Math.min(delay * 1.5, 5000)
  }
  throw new Error('Processing is taking longer than expected. Please check back shortly.')
}
