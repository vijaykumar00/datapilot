/**
 * authSession.js — shared access-token handling for every API call.
 *
 * - The refresh token lives ONLY in the HttpOnly `dp_refresh` cookie set by the
 *   API; JavaScript never stores or reads it.
 * - The short-lived access token is kept in localStorage so API helpers outside
 *   React (zustand store, billing client) can attach it.
 * - `authedFetch` retries a request once after a silent cookie refresh when the
 *   API answers 401, so an expired access token never surfaces as an error.
 * - Refreshes are de-duplicated inside a tab (shared promise) and across tabs
 *   (Web Locks), because refresh tokens rotate and a parallel refresh would look
 *   like token reuse.
 */
import { apiUrl } from './apiConfig.js'

export const AUTH_KEYS = {
  ACCESS_TOKEN: 'dp_access_token',
  LEGACY_REFRESH_TOKEN: 'dp_refresh_token',
  USER: 'dp_user',
  WORKSPACE_ID: 'dp_workspace_id',
  GUEST_TOKEN: 'dp_guest_token',
  GUEST_SESSION_ID: 'dp_guest_session_id',
}

export const AUTH_REFRESHED_EVENT = 'dp-auth-refreshed'
export const AUTH_EXPIRED_EVENT = 'dp-auth-expired'

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

export function getAccessToken() {
  return hasWindow() ? safeGet(window.localStorage, AUTH_KEYS.ACCESS_TOKEN) : null
}

export function getWorkspaceId() {
  return hasWindow() ? safeGet(window.localStorage, AUTH_KEYS.WORKSPACE_ID) : null
}

export function getGuestToken() {
  return hasWindow() ? safeGet(window.sessionStorage, AUTH_KEYS.GUEST_TOKEN) : null
}

/** Remove refresh tokens persisted by older builds (they now live in an HttpOnly cookie). */
export function takeLegacyRefreshToken() {
  if (!hasWindow()) return null
  const token = safeGet(window.sessionStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN)
    || safeGet(window.localStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN)
  safeSet(window.sessionStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN, null)
  safeSet(window.localStorage, AUTH_KEYS.LEGACY_REFRESH_TOKEN, null)
  return token
}

export function storeSession(data) {
  if (!hasWindow()) return
  const user = {
    user_id: data.user_id,
    email: data.email,
    full_name: data.full_name || null,
    phone_number: data.phone_number || null,
  }
  safeSet(window.localStorage, AUTH_KEYS.ACCESS_TOKEN, data.access_token)
  safeSet(window.localStorage, AUTH_KEYS.USER, JSON.stringify(user))
  if (data.workspace_id) safeSet(window.localStorage, AUTH_KEYS.WORKSPACE_ID, data.workspace_id)
  takeLegacyRefreshToken()
  return user
}

export function clearSession() {
  if (!hasWindow()) return
  safeSet(window.localStorage, AUTH_KEYS.ACCESS_TOKEN, null)
  safeSet(window.localStorage, AUTH_KEYS.USER, null)
  safeSet(window.localStorage, AUTH_KEYS.WORKSPACE_ID, null)
  takeLegacyRefreshToken()
}

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms))

async function requestRefresh() {
  const legacy = takeLegacyRefreshToken()
  const body = { workspace_id: getWorkspaceId() }
  if (legacy) body.refresh_token = legacy

  for (let attempt = 0; attempt < 3; attempt += 1) {
    let resp
    try {
      resp = await fetch(apiUrl('/auth/refresh'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
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
 * Obtain a fresh access token from the refresh cookie.
 * Resolves to the token, or null when the session is gone (an
 * AUTH_EXPIRED_EVENT is dispatched) or the API is temporarily unreachable.
 */
export function refreshAccessToken() {
  if (inflight) return inflight
  const startedWith = getAccessToken()

  const run = async () => {
    // Another tab may have refreshed while this one waited for the lock.
    const current = getAccessToken()
    if (current && current !== startedWith) return current

    const result = await requestRefresh()
    if (result.ok) {
      const user = storeSession(result.data)
      if (hasWindow()) {
        window.dispatchEvent(new CustomEvent(AUTH_REFRESHED_EVENT, { detail: { ...result.data, user } }))
      }
      return result.data.access_token
    }
    if (!result.transient) {
      clearSession()
      if (hasWindow()) window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
    return null
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

function buildHeaders(extra = {}) {
  const headers = { ...extra }
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const guestToken = getGuestToken()
  if (guestToken && !token) headers['X-Guest-Token'] = guestToken
  const workspaceId = getWorkspaceId()
  if (workspaceId && token) headers['X-Workspace-ID'] = workspaceId
  return headers
}

/** fetch() against the API with auth headers and one transparent refresh-and-retry on 401. */
export async function authedFetch(path, options = {}) {
  const { headers: extraHeaders, ...rest } = options
  const first = buildHeaders(extraHeaders)
  const resp = await fetch(apiUrl(path), { credentials: 'include', ...rest, headers: first })
  if (resp.status !== 401 || !first.Authorization) return resp

  const token = await refreshAccessToken()
  if (!token) return resp
  return fetch(apiUrl(path), { credentials: 'include', ...rest, headers: buildHeaders(extraHeaders) })
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
