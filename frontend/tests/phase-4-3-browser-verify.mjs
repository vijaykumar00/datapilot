import assert from 'node:assert/strict'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const evidenceDir = resolve(root, 'test-results', 'phase-4-3')
const previewPort = 4174
const debugPort = 9334
const baseUrl = `http://127.0.0.1:${previewPort}`
const chromePathCandidates = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
]

function sleep(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms))
}

async function requestJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) throw new Error(`${url} returned ${response.status}`)
  return response.json()
}

async function waitForHttp(url, timeoutMs = 20_000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {}
    await sleep(250)
  }
  throw new Error(`Timed out waiting for ${url}`)
}

function findChromePath() {
  const chromePath = chromePathCandidates.find((candidate) => existsSync(candidate))
  if (!chromePath) throw new Error('Chrome or Edge executable was not found')
  return chromePath
}

function spawnProcess(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: root,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    ...options,
  })
  child.stdout?.on('data', (chunk) => process.stdout.write(chunk))
  child.stderr?.on('data', (chunk) => process.stderr.write(chunk))
  return child
}

function spawnNpm(args) {
  return spawnProcess('npm.cmd', args, { shell: true })
}

function killProcessTree(child) {
  if (!child?.pid) return
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
    return
  }
  child.kill('SIGTERM')
}

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl)
    this.nextId = 1
    this.pending = new Map()
    this.events = new Map()
  }

  async open() {
    await new Promise((resolvePromise, reject) => {
      this.ws.addEventListener('open', resolvePromise, { once: true })
      this.ws.addEventListener('error', reject, { once: true })
    })
    this.ws.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        const { resolve: resolvePromise, reject } = this.pending.get(message.id)
        this.pending.delete(message.id)
        if (message.error) reject(new Error(message.error.message))
        else resolvePromise(message.result || {})
        return
      }
      if (message.method && this.events.has(message.method)) {
        for (const listener of this.events.get(message.method)) listener(message.params || {})
      }
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolvePromise, reject) => {
      this.pending.set(id, { resolve: resolvePromise, reject })
    })
  }

  once(method) {
    return new Promise((resolvePromise) => {
      const listener = (params) => {
        this.events.set(method, (this.events.get(method) || []).filter((item) => item !== listener))
        resolvePromise(params)
      }
      this.events.set(method, [...(this.events.get(method) || []), listener])
    })
  }

  close() {
    this.ws.close()
  }
}

async function createBrowserTab() {
  await waitForHttp(`http://127.0.0.1:${debugPort}/json/version`)
  const target = await requestJson(`http://127.0.0.1:${debugPort}/json/new?${baseUrl}/`, { method: 'PUT' })
  const tab = new CdpClient(target.webSocketDebuggerUrl)
  await tab.open()
  await tab.send('Page.enable')
  await tab.send('Runtime.enable')
  await tab.send('Log.enable')
  await tab.send('Page.addScriptToEvaluateOnNewDocument', { source: billingMockScript() })
  return tab
}

function billingMockScript() {
  return `
    (() => {
      const plans = [
        { plan_id: 'free', name: 'Free', description: 'Explore DataPilot with starter limits.', monthly_price_cents: 0, annual_price_cents: 0, is_public: true, is_active: true, limits: { ai_prompt_count: 50, query_count: 50, upload_count: 5, dataset_count: 3, report_count: 2, export_count: 3, storage_bytes: 524288000, chart_count: 10, member_count: 1, api_usage_count: 0 } },
        { plan_id: 'pro', name: 'Pro', description: 'For analysts who need more prompts, reports, and storage.', monthly_price_cents: 1900, annual_price_cents: 19000, is_public: true, is_active: true, limits: { ai_prompt_count: 1000, query_count: 1000, upload_count: 100, dataset_count: 100, report_count: 50, export_count: 100, storage_bytes: 10737418240, chart_count: 200, member_count: 3, api_usage_count: 1000 } },
        { plan_id: 'team', name: 'Team', description: 'Collaboration, higher limits, and shared workspaces.', monthly_price_cents: 4900, annual_price_cents: 49000, is_public: true, is_active: true, limits: { ai_prompt_count: 5000, query_count: 5000, upload_count: 500, dataset_count: 500, report_count: 250, export_count: 500, storage_bytes: 53687091200, chart_count: 1000, member_count: 10, api_usage_count: 10000 } },
        { plan_id: 'enterprise', name: 'Enterprise', description: 'Custom limits, controls, and deployment support.', monthly_price_cents: 0, annual_price_cents: 0, is_public: true, is_active: true, limits: { ai_prompt_count: -1, query_count: -1, upload_count: -1, dataset_count: -1, report_count: -1, export_count: -1, storage_bytes: -1, chart_count: -1, member_count: -1, api_usage_count: -1 } }
      ];
      const scenarioData = {
        free: { plan: plans[0], subscription: { status: 'free', plan_id: 'free', current_period_start: '2026-07-01T00:00:00', current_period_end: '2026-08-01T00:00:00', renews_at: null, cancel_at_period_end: false, canceled_at: null }, trial: { active: false, expired: false, ends_at: null }, billing: { payment_status: 'free', portal_available: false }, usage: { ai_prompt_count: 8, query_count: 8, upload_count: 2, dataset_count: 1, report_count: 1, export_count: 0, storage_bytes: 120000000, chart_count: 2, member_count: 1, api_usage_count: 0 }, remaining_quota: { ai_prompt_count: 42, query_count: 42, upload_count: 3, dataset_count: 2, report_count: 1, export_count: 3, storage_bytes: 404288000, chart_count: 8, member_count: 0, api_usage_count: 0 }, limits: plans[0].limits, features: {} },
        trial: { plan: plans[1], subscription: { status: 'trialing', plan_id: 'pro', current_period_start: '2026-07-17T00:00:00', current_period_end: '2026-07-31T00:00:00', renews_at: '2026-07-31T00:00:00', cancel_at_period_end: false, canceled_at: null }, trial: { active: true, expired: false, ends_at: '2026-07-31T00:00:00' }, billing: { payment_status: 'trialing', portal_available: true }, usage: { ai_prompt_count: 70, query_count: 70, upload_count: 8, dataset_count: 5, report_count: 4, export_count: 2, storage_bytes: 500000000, chart_count: 15, member_count: 2, api_usage_count: 20 }, remaining_quota: { ai_prompt_count: 930, query_count: 930, upload_count: 92, dataset_count: 95, report_count: 46, export_count: 98, storage_bytes: 10237418240, chart_count: 185, member_count: 1, api_usage_count: 980 }, limits: plans[1].limits, features: {} },
        paid: { plan: plans[1], subscription: { status: 'active', plan_id: 'pro', current_period_start: '2026-07-01T00:00:00', current_period_end: '2026-08-01T00:00:00', renews_at: '2026-08-01T00:00:00', cancel_at_period_end: false, canceled_at: null }, trial: { active: false, expired: false, ends_at: null }, billing: { payment_status: 'active', portal_available: true }, usage: { ai_prompt_count: 400, query_count: 400, upload_count: 30, dataset_count: 15, report_count: 10, export_count: 15, storage_bytes: 1000000000, chart_count: 40, member_count: 2, api_usage_count: 100 }, remaining_quota: { ai_prompt_count: 600, query_count: 600, upload_count: 70, dataset_count: 85, report_count: 40, export_count: 85, storage_bytes: 9737418240, chart_count: 160, member_count: 1, api_usage_count: 900 }, limits: plans[1].limits, features: {} },
        past_due: { plan: plans[1], subscription: { status: 'past_due', plan_id: 'pro', current_period_start: '2026-07-01T00:00:00', current_period_end: '2026-08-01T00:00:00', renews_at: '2026-08-01T00:00:00', cancel_at_period_end: false, canceled_at: null }, trial: { active: false, expired: false, ends_at: null }, billing: { payment_status: 'past_due', portal_available: true }, usage: { ai_prompt_count: 810, query_count: 810, upload_count: 88, dataset_count: 90, report_count: 45, export_count: 90, storage_bytes: 9800000000, chart_count: 170, member_count: 3, api_usage_count: 800 }, remaining_quota: { ai_prompt_count: 190, query_count: 190, upload_count: 12, dataset_count: 10, report_count: 5, export_count: 10, storage_bytes: 937418240, chart_count: 30, member_count: 0, api_usage_count: 200 }, limits: plans[1].limits, features: {} },
        exhausted: { plan: plans[0], subscription: { status: 'expired', plan_id: 'free', current_period_start: '2026-07-01T00:00:00', current_period_end: '2026-08-01T00:00:00', renews_at: null, cancel_at_period_end: false, canceled_at: null }, trial: { active: false, expired: true, ends_at: '2026-07-16T00:00:00' }, billing: { payment_status: 'expired', portal_available: false }, usage: { ai_prompt_count: 50, query_count: 50, upload_count: 5, dataset_count: 3, report_count: 2, export_count: 3, storage_bytes: 524288000, chart_count: 10, member_count: 1, api_usage_count: 0 }, remaining_quota: { ai_prompt_count: 0, query_count: 0, upload_count: 0, dataset_count: 0, report_count: 0, export_count: 0, storage_bytes: 0, chart_count: 0, member_count: 0, api_usage_count: 0 }, limits: plans[0].limits, features: {} }
      };
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (input, init = {}) => {
        const url = String(input);
        const scenario = localStorage.getItem('dp_billing_scenario') || 'free';
        const json = (body, delay = 0) => new Promise((resolve) => setTimeout(() => resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })), delay));
        if (url.includes('/billing/plans')) return json({ plans });
        if (url.includes('/billing/current') || url.includes('/billing/status')) return json({ workspace_id: 'browser-workspace', ...scenarioData[scenario] });
        if (url.includes('/billing/checkout')) return json({ checkout_url: window.location.origin + '/app/settings/billing?checkout=success' }, 650);
        if (url.includes('/billing/portal')) return json({ portal_url: window.location.origin + '/app/settings/billing?portal=returned' }, 650);
        return originalFetch(input, init);
      };
    })();
  `
}

async function setViewport(tab, width, height) {
  await tab.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 768 })
}

async function navigate(tab, path, width = 1024, height = 768) {
  await setViewport(tab, width, height)
  const loaded = tab.once('Page.loadEventFired')
  await tab.send('Page.navigate', { url: `${baseUrl}${path}` })
  await loaded
  await sleep(500)
}

async function evaluate(tab, expression) {
  const result = await tab.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser evaluation failed')
  return result.result.value
}

async function screenshot(tab, name) {
  const result = await tab.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  await writeFile(resolve(evidenceDir, `${name}.png`), Buffer.from(result.data, 'base64'))
}

async function setAuth(tab, scenario) {
  await evaluate(tab, `(() => {
    localStorage.setItem('dp_access_token', 'phase-4-3-token');
    localStorage.setItem('dp_refresh_token', 'phase-4-3-refresh');
    localStorage.setItem('dp_workspace_id', 'browser-workspace');
    localStorage.setItem('dp_user', JSON.stringify({ user_id: 'browser-user', email: 'billing@datapilot.test', full_name: 'Billing Tester' }));
    localStorage.setItem('dp_billing_scenario', '${scenario}');
    sessionStorage.clear();
  })()`)
}

async function main() {
  await mkdir(evidenceDir, { recursive: true })
  const preview = spawnNpm(['run', 'preview', '--', '--host', '127.0.0.1', '--port', String(previewPort)])
  const userDataDir = resolve(tmpdir(), `datapilot-phase-4-3-${Date.now()}`)
  const chrome = spawnProcess(findChromePath(), [
    '--headless=new',
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ], { cwd: root })

  let tab
  const failures = []
  try {
    await waitForHttp(`${baseUrl}/`)
    tab = await createBrowserTab()
    const browserErrors = []
    tab.events.set('Runtime.exceptionThrown', [(params) => browserErrors.push(params.exceptionDetails?.text || 'Runtime exception')])
    tab.events.set('Log.entryAdded', [(params) => { if (params.entry?.level === 'error') browserErrors.push(params.entry.text) }])

    for (const width of [320, 375, 768, 1024, 1280, 1440]) {
      await navigate(tab, '/pricing', width, 900)
      const check = await evaluate(tab, `(() => ({
        noOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        cards: document.querySelectorAll('.pricing-plan-card').length,
        buttons: document.querySelectorAll('.pricing-plan-card a, .pricing-plan-card button').length
      }))()`)
      assert.equal(check.noOverflow, true, `pricing overflow at ${width}`)
      assert.equal(check.cards, 4)
      assert.ok(check.buttons >= 4)
    }
    await screenshot(tab, 'pricing-mobile')
    await navigate(tab, '/pricing', 1440, 900)
    await screenshot(tab, 'pricing-desktop')

    const stateScreens = [
      ['free-plan-billing-page', 'free'],
      ['trial-billing-page', 'trial'],
      ['paid-plan-billing-page', 'paid'],
      ['usage-near-limit', 'past_due'],
      ['usage-exhausted', 'exhausted'],
      ['past-due-warning', 'past_due'],
      ['expired-trial-state', 'exhausted'],
    ]
    for (const [name, scenario] of stateScreens) {
      await setAuth(tab, scenario)
      await navigate(tab, '/app/settings/billing', name === 'free-plan-billing-page' ? 375 : 1280, 900)
      const billingState = await evaluate(tab, `(() => ({
        dashboard: !!document.querySelector('[data-testid="billing-dashboard"]'),
        progressBars: document.querySelectorAll('[role="progressbar"]').length,
        noOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        hasManage: document.body.textContent.includes('Manage billing'),
        hasUpgrade: document.body.textContent.includes('Upgrade') || document.body.textContent.includes('Change plan'),
        hasWarningText: document.body.textContent.includes('Payment past due') || document.body.textContent.includes('Limit exhausted') || document.body.textContent.includes('Trial expired') || document.body.textContent.includes('Trial active')
      }))()`)
      assert.equal(billingState.dashboard, true)
      assert.ok(billingState.progressBars >= 8)
      assert.equal(billingState.noOverflow, true)
      assert.equal(billingState.hasManage, true)
      assert.equal(billingState.hasUpgrade, true)
      await screenshot(tab, name)
    }

    await setAuth(tab, 'free')
    await navigate(tab, '/app/settings/billing', 1280, 900)
    await evaluate(tab, `Array.from(document.querySelectorAll('button')).find((button) => button.textContent.includes('Upgrade'))?.click()`)
    await sleep(100)
    assert.equal(await evaluate(tab, `document.body.textContent.includes('Starting checkout')`), true)
    await screenshot(tab, 'checkout-loading-state')

    await setAuth(tab, 'paid')
    await navigate(tab, '/app/settings/billing', 1280, 900)
    await evaluate(tab, `Array.from(document.querySelectorAll('button')).find((button) => button.textContent.includes('Manage billing'))?.click()`)
    await sleep(100)
    assert.equal(await evaluate(tab, `document.body.textContent.includes('Opening portal')`), true)
    await screenshot(tab, 'portal-loading-state')

    const security = await evaluate(tab, `(() => ({
      noSecrets: !document.documentElement.innerHTML.match(/sk_live|sk_test|whsec|STRIPE_SECRET|WEBHOOK_SECRET/i),
      checkoutViaBackend: !document.documentElement.innerHTML.includes('stripe.com/v1')
    }))()`)
    assert.deepEqual(security, { noSecrets: true, checkoutViaBackend: true })
    assert.deepEqual(browserErrors, [])

    await writeFile(resolve(evidenceDir, 'browser-verification.json'), JSON.stringify({
      baseUrl,
      screenshots: [
        'pricing-desktop.png',
        'pricing-mobile.png',
        ...stateScreens.map(([name]) => `${name}.png`),
        'checkout-loading-state.png',
        'portal-loading-state.png',
      ],
      statesChecked: stateScreens.map(([, scenario]) => scenario),
      viewportsChecked: [320, 375, 768, 1024, 1280, 1440],
      security,
    }, null, 2))
  } catch (error) {
    failures.push(error)
  } finally {
    tab?.close()
    killProcessTree(chrome)
    killProcessTree(preview)
    await sleep(500)
    await rm(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 }).catch(() => {})
  }

  if (failures.length) throw failures[0]
}

await main()
console.log(`Phase 4.3 browser verification passed. Evidence written to ${evidenceDir}`)
process.exit(0)
