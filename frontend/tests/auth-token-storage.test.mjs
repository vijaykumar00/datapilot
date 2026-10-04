import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

const SOURCES = [
  '../src/contexts/AuthContext.jsx',
  '../src/lib/authSession.js',
  '../src/lib/billingClient.js',
  '../src/hooks/useDataPilot.js',
]

test('no access or refresh token is ever written to JS-readable storage or sent as a bearer header', () => {
  for (const path of SOURCES) {
    const source = read(path)
    assert.doesNotMatch(source, /(localStorage|sessionStorage)\.setItem\([^)]*(ACCESS|REFRESH|access_token|refresh_token)/i, path)
    assert.doesNotMatch(source, /Authorization['"]?\]?\s*[:=]\s*`Bearer/, path)
    assert.doesNotMatch(source, /data\.access_token|data\.refresh_token/, path)
  }
  const session = read('../src/lib/authSession.js')
  // Tokens left behind by older builds are removed.
  assert.match(session, /takeLegacyTokens/)
  // Unsafe requests carry the double-submit CSRF token; credentials are always included.
  assert.match(session, /X-CSRF-Token/)
  assert.match(session, /credentials: 'include'/)
})

test('credential-issuing calls ask for cookie-only sessions', () => {
  const authContext = read('../src/contexts/AuthContext.jsx')
  for (const endpoint of ["apiUrl('/auth/login')", 'apiUrl(`/auth/oauth/${normalizedProvider}/callback`)', "apiUrl('/auth/otp/verify')", "apiUrl('/guest/convert')"]) {
    const at = authContext.indexOf(endpoint)
    assert.ok(at > 0, endpoint)
    assert.match(authContext.slice(at, at + 400), /SESSION_MODE_HEADERS/, endpoint)
  }
  assert.match(authContext, /\/auth\/logout[\s\S]*credentials: 'include'/)
})

test('social and OTP auth flows are still wired', () => {
  const authContext = read('../src/contexts/AuthContext.jsx')
  assert.match(authContext, /beginSocialLogin/)
  assert.match(authContext, /completeSocialLogin/)
  assert.match(authContext, /requestPhoneOtp/)
  assert.match(authContext, /verifyPhoneOtp/)
  assert.match(authContext, /\/auth\/oauth\/\$\{normalizedProvider\}\/start/)
  assert.match(authContext, /\/auth\/otp\/request/)
  assert.match(authContext, /\/auth\/otp\/verify/)
})
