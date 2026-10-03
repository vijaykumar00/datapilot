import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('refresh tokens are never persisted in JS-readable storage', () => {
  const authContext = read('../src/contexts/AuthContext.jsx')
  const session = read('../src/lib/authSession.js')

  for (const source of [authContext, session]) {
    assert.doesNotMatch(source, /(localStorage|sessionStorage)\.setItem\([^)]*REFRESH/)
    assert.doesNotMatch(source, /storeRefreshToken/)
  }
  // Tokens left behind by older builds are removed.
  assert.match(session, /takeLegacyRefreshToken/)
  assert.match(session, /LEGACY_REFRESH_TOKEN/)
  // Refresh and logout use the HttpOnly cookie.
  assert.match(session, /\/auth\/refresh[\s\S]*credentials: 'include'/)
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

test('expired access tokens are refreshed once and requests retried', () => {
  const session = read('../src/lib/authSession.js')
  assert.match(session, /resp\.status !== 401/)
  assert.match(session, /refreshAccessToken\(\)/)
  // Cross-tab de-duplication: rotated refresh tokens must not be replayed in parallel.
  assert.match(session, /navigator\?\.locks\?\.request/)
  assert.match(session, /resp\.status === 409/)
})
