import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('frontend API calls are centralized behind same-origin /api by default', () => {
  const apiConfig = read('../src/lib/apiConfig.js')
  const authContext = read('../src/contexts/AuthContext.jsx')
  const billingClient = read('../src/lib/billingClient.js')
  const dataPilotHook = read('../src/hooks/useDataPilot.js')
  const savedReports = read('../src/components/SavedReports.jsx')
  const app = read('../src/App.jsx')

  assert.match(apiConfig, /DEFAULT_API_BASE = '\/api'/)
  assert.match(apiConfig, /VITE_API_URL/)
  assert.match(apiConfig, /must not point to a loopback host/)

  for (const source of [authContext, billingClient, dataPilotHook, savedReports, app]) {
    assert.match(source, /apiUrl/)
    assert.doesNotMatch(source, /http:\/\/localhost:8001/)
    assert.doesNotMatch(source, /http:\/\/127\.0\.0\.1:8001/)
    assert.doesNotMatch(source, /API_BASES/)
    assert.doesNotMatch(source, /__DATAPILOT_API_PORT__/)
  }

  assert.match(app, /API_BASE/)
  assert.doesNotMatch(app, /VITE_API_URL \|\| ''/)
})

test('Docker, Vite, and Nginx wire /api to the backend explicitly', () => {
  const vite = read('../vite.config.js')
  const dockerfile = read('../Dockerfile')
  const compose = read('../../docker-compose.yml')
  const nginx = read('../nginx.conf')
  const envExample = read('../.env.example')

  assert.match(vite, /'\/api'/)
  assert.match(vite, /rewrite: \(path\) => path\.replace/)
  assert.match(dockerfile, /ARG VITE_API_URL=\/api/)
  assert.match(dockerfile, /ENV VITE_API_URL=\$VITE_API_URL/)
  assert.match(compose, /VITE_API_URL: \$\{VITE_API_URL:-\/api\}/)
  assert.match(nginx, /location \/api\//)
  assert.match(nginx, /proxy_pass http:\/\/backend:8000\//)
  assert.match(envExample, /VITE_API_URL=\/api/)
})
