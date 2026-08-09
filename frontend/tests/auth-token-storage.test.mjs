import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('refresh tokens are migrated out of persistent localStorage', () => {
  const authContext = read('../src/contexts/AuthContext.jsx')

  assert.match(authContext, /function readRefreshToken/)
  assert.match(authContext, /sessionStorage\.setItem\(STORAGE_KEYS\.REFRESH_TOKEN/)
  assert.match(authContext, /localStorage\.removeItem\(STORAGE_KEYS\.REFRESH_TOKEN/)
  assert.doesNotMatch(authContext, /localStorage\.setItem\(STORAGE_KEYS\.REFRESH_TOKEN/)
})
