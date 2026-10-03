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
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail } }

const session = await import('../src/lib/authSession.js')

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  events.length = 0
})

test('401 triggers one cookie refresh and the request is retried with the new token', async () => {
  window.localStorage.setItem('dp_access_token', 'old')
  window.localStorage.setItem('dp_workspace_id', 'ws-1')
  const calls = []
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, auth: opts.headers?.Authorization, credentials: opts.credentials, body: opts.body })
    if (url.endsWith('/auth/refresh')) {
      return jsonResponse(200, { access_token: 'new', refresh_token: 'ignored', user_id: 'u', email: 'a@b.c', workspace_id: 'ws-1' })
    }
    return opts.headers.Authorization === 'Bearer new' ? jsonResponse(200, { ok: true }) : jsonResponse(401, { error: 'expired' })
  }
  const resp = await session.authedFetch('/files')
  assert.equal(resp.status, 200)
  assert.deepEqual(calls.map(c => c.url), ['/api/files', '/api/auth/refresh', '/api/files'])
  assert.equal(calls[1].credentials, 'include')
  assert.equal(JSON.parse(calls[1].body).workspace_id, 'ws-1')
  assert.equal(window.localStorage.getItem('dp_access_token'), 'new')
  // The refresh token from the body is never persisted.
  assert.equal(window.localStorage.getItem('dp_refresh_token'), null)
  assert.equal(window.sessionStorage.getItem('dp_refresh_token'), null)
  assert.ok(events.includes(session.AUTH_REFRESHED_EVENT))
})

test('concurrent 401s share a single refresh', async () => {
  window.localStorage.setItem('dp_access_token', 'old')
  let refreshes = 0
  globalThis.fetch = async (url, opts) => {
    if (url.endsWith('/auth/refresh')) {
      refreshes += 1
      await new Promise(r => setTimeout(r, 10))
      return jsonResponse(200, { access_token: 'new', user_id: 'u', email: 'e', workspace_id: 'w' })
    }
    return opts.headers.Authorization === 'Bearer new' ? jsonResponse(200, {}) : jsonResponse(401, {})
  }
  const results = await Promise.all([session.authedFetch('/a'), session.authedFetch('/b'), session.authedFetch('/c')])
  assert.deepEqual(results.map(r => r.status), [200, 200, 200])
  assert.equal(refreshes, 1)
})

test('a dead session clears credentials and signals expiry; network errors do not log out', async () => {
  window.localStorage.setItem('dp_access_token', 'old')
  globalThis.fetch = async () => { throw new TypeError('offline') }
  assert.equal(await session.refreshAccessToken(), null)
  assert.equal(window.localStorage.getItem('dp_access_token'), 'old')

  globalThis.fetch = async () => jsonResponse(401, { error: 'Invalid or expired refresh token' })
  assert.equal(await session.refreshAccessToken(), null)
  assert.equal(window.localStorage.getItem('dp_access_token'), null)
  assert.ok(events.includes(session.AUTH_EXPIRED_EVENT))
})

test('legacy stored refresh tokens are sent once and then deleted', async () => {
  window.sessionStorage.setItem('dp_refresh_token', 'legacy')
  let sent
  globalThis.fetch = async (url, opts) => {
    sent = JSON.parse(opts.body)
    return jsonResponse(200, { access_token: 't', user_id: 'u', email: 'e', workspace_id: 'w' })
  }
  assert.equal(await session.refreshAccessToken(), 't')
  assert.equal(sent.refresh_token, 'legacy')
  assert.equal(window.sessionStorage.getItem('dp_refresh_token'), null)
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
