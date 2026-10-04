import assert from 'node:assert/strict'
import { test, beforeEach } from 'node:test'

// Minimal browser globals for lib/authSession.js
function memoryStorage() {
  const data = new Map()
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    clear: () => data.clear(),
  }
}

const events = []
globalThis.window = {
  localStorage: memoryStorage(),
  sessionStorage: memoryStorage(),
  navigator: {},
  dispatchEvent: (e) => events.push(e.type),
}
globalThis.document = { cookie: '' }
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail } }

const session = await import('../src/lib/authSession.js')

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function signedIn() {
  window.localStorage.setItem('dp_user', JSON.stringify({ user_id: 'u', email: 'a@b.c' }))
  window.localStorage.setItem('dp_workspace_id', 'ws-1')
  document.cookie = 'dp_csrf=csrf-123; other=1'
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  document.cookie = ''
  events.length = 0
})

test('requests use cookies only: no Authorization header, CSRF only on unsafe methods', async () => {
  signedIn()
  const calls = []
  globalThis.fetch = async (url, opts) => { calls.push({ url, opts }); return jsonResponse(200, {}) }
  await session.authedFetch('/files')
  await session.authedFetch('/files/1', { method: 'DELETE' })
  for (const { opts } of calls) {
    assert.equal(opts.credentials, 'include')
    assert.equal(opts.headers.Authorization, undefined)
    assert.equal(opts.headers['X-Workspace-ID'], 'ws-1')
  }
  assert.equal(calls[0].opts.headers['X-CSRF-Token'], undefined)
  assert.equal(calls[1].opts.headers['X-CSRF-Token'], 'csrf-123')
})

test('401 triggers one cookie refresh (with CSRF + session mode) and the request is retried', async () => {
  signedIn()
  const calls = []
  let refreshed = false
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts })
    if (url.endsWith('/auth/refresh')) {
      refreshed = true
      return jsonResponse(200, { access_token: null, refresh_token: null, user_id: 'u', email: 'a@b.c', workspace_id: 'ws-1' })
    }
    return refreshed ? jsonResponse(200, { ok: true }) : jsonResponse(401, { error: 'expired' })
  }
  const resp = await session.authedFetch('/files')
  assert.equal(resp.status, 200)
  assert.deepEqual(calls.map(c => c.url), ['/api/files', '/api/auth/refresh', '/api/files'])
  const refresh = calls[1].opts
  assert.equal(refresh.credentials, 'include')
  assert.equal(refresh.headers['X-CSRF-Token'], 'csrf-123')
  assert.equal(refresh.headers['X-Session-Mode'], 'cookie')
  assert.equal(JSON.parse(refresh.body).workspace_id, 'ws-1')
  // No token of any kind is persisted in JS-readable storage.
  for (const key of ['dp_access_token', 'dp_refresh_token']) {
    assert.equal(window.localStorage.getItem(key), null)
    assert.equal(window.sessionStorage.getItem(key), null)
  }
  assert.ok(events.includes(session.AUTH_REFRESHED_EVENT))
})

test('concurrent 401s share a single refresh', async () => {
  signedIn()
  let refreshes = 0
  let fresh = false
  globalThis.fetch = async (url) => {
    if (url.endsWith('/auth/refresh')) {
      refreshes += 1
      await new Promise(r => setTimeout(r, 10))
      fresh = true
      return jsonResponse(200, { user_id: 'u', email: 'e', workspace_id: 'ws-1' })
    }
    return fresh ? jsonResponse(200, {}) : jsonResponse(401, {})
  }
  const results = await Promise.all([session.authedFetch('/a'), session.authedFetch('/b'), session.authedFetch('/c')])
  assert.deepEqual(results.map(r => r.status), [200, 200, 200])
  assert.equal(refreshes, 1)
})

test('a refresh done by another tab while waiting is reused, not repeated', async () => {
  signedIn()
  window.localStorage.setItem('dp_session_epoch', '1')
  let refreshes = 0
  // Simulate the Web Lock being held by another tab that refreshes meanwhile.
  window.navigator.locks = {
    request: async (_name, fn) => { window.localStorage.setItem('dp_session_epoch', '2'); return fn() },
  }
  globalThis.fetch = async () => { refreshes += 1; return jsonResponse(200, {}) }
  assert.equal(await session.refreshSession(), true)
  assert.equal(refreshes, 0)
  delete window.navigator.locks
})

test('a dead session clears profile and signals expiry; network errors do not log out', async () => {
  signedIn()
  globalThis.fetch = async () => { throw new TypeError('offline') }
  assert.equal(await session.refreshSession(), false)
  assert.ok(window.localStorage.getItem('dp_user'))

  globalThis.fetch = async () => jsonResponse(401, { error: 'Invalid or expired refresh token' })
  assert.equal(await session.refreshSession(), false)
  assert.equal(window.localStorage.getItem('dp_user'), null)
  assert.ok(events.includes(session.AUTH_EXPIRED_EVENT))
})

test('guests send their guest token and are never refreshed', async () => {
  window.sessionStorage.setItem('dp_guest_token', 'g-1')
  const calls = []
  globalThis.fetch = async (url, opts) => { calls.push({ url, opts }); return jsonResponse(401, {}) }
  const resp = await session.authedFetch('/files')
  assert.equal(resp.status, 401)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].opts.headers['X-Guest-Token'], 'g-1')
})

test('legacy stored tokens are migrated once through the refresh body and then deleted', async () => {
  signedIn()
  window.localStorage.setItem('dp_access_token', 'legacy-access')
  window.sessionStorage.setItem('dp_refresh_token', 'legacy')
  let sent
  globalThis.fetch = async (url, opts) => {
    sent = JSON.parse(opts.body)
    return jsonResponse(200, { user_id: 'u', email: 'e', workspace_id: 'w' })
  }
  assert.equal(await session.refreshSession(), true)
  assert.equal(sent.refresh_token, 'legacy')
  assert.equal(window.sessionStorage.getItem('dp_refresh_token'), null)
  assert.equal(window.localStorage.getItem('dp_access_token'), null)
})

test('readApiError handles structured, string and non-JSON errors', async () => {
  assert.equal(await session.readApiError(jsonResponse(400, { error: 'Bad thing' })), 'Bad thing')
  assert.equal(await session.readApiError(jsonResponse(400, { detail: { message: 'Nested' } })), 'Nested')
  assert.equal(await session.readApiError(new Response('<html>413</html>', { status: 413 })), 'File is too large to upload.')
  assert.match(await session.readApiError(new Response('<html>bad gateway</html>', { status: 502 })), /temporarily unavailable/)
})

test('waitForJob polls until success and surfaces job failures', async () => {
  let polls = 0
  globalThis.fetch = async () => {
    polls += 1
    return jsonResponse(200, polls < 2 ? { status: 'running' } : { status: 'succeeded', result: { file_id: 'f' } })
  }
  const job = await session.waitForJob('job-1', { timeoutMs: 10_000 })
  assert.equal(job.result.file_id, 'f')

  globalThis.fetch = async () => jsonResponse(200, { status: 'failed', error: 'Could not parse file' })
  await assert.rejects(session.waitForJob('job-2'), /Could not parse file/)
})
