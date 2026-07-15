import assert from 'node:assert/strict'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const evidenceDir = resolve(root, 'test-results', 'sprint-3-2')
const previewPort = 4173
const debugPort = 9333
const baseUrl = `http://127.0.0.1:${previewPort}`
const chromePathCandidates = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
]

const screenshotTargets = [
  ['homepage-desktop', '/', 1440, 900],
  ['homepage-mobile', '/', 375, 812],
  ['features-page', '/features', 1024, 768],
  ['security-page', '/security', 1024, 768],
  ['pricing-page', '/pricing', 1024, 768],
  ['public-404-page', '/missing-route', 1024, 768],
]

const publicRoutes = [
  '/',
  '/features',
  '/use-cases',
  '/security',
  '/pricing',
  '/about',
  '/contact',
  '/docs',
  '/legal/privacy',
  '/legal/terms',
  '/legal/cookie-policy',
  '/legal/acceptable-use',
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
    spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
      stdio: 'ignore',
      windowsHide: true,
    })
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

async function createBrowserTab(chrome) {
  await waitForHttp(`http://127.0.0.1:${debugPort}/json/version`)
  const target = await requestJson(`http://127.0.0.1:${debugPort}/json/new?${baseUrl}/`, {
    method: 'PUT',
  })
  const tab = new CdpClient(target.webSocketDebuggerUrl)
  await tab.open()
  await tab.send('Page.enable')
  await tab.send('Runtime.enable')
  await tab.send('Log.enable')
  await tab.send('Input.setIgnoreInputEvents', { ignore: false })
  return tab
}

async function setViewport(tab, width, height) {
  await tab.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 768,
  })
}

async function navigate(tab, path, width = 1024, height = 768) {
  await setViewport(tab, width, height)
  const loaded = tab.once('Page.loadEventFired')
  await tab.send('Page.navigate', { url: `${baseUrl}${path}` })
  await loaded
  await sleep(250)
}

async function evaluate(tab, expression) {
  const result = await tab.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Browser evaluation failed')
  }
  return result.result.value
}

async function press(tab, key, modifiers = 0) {
  await tab.send('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key,
    code: key === ' ' ? 'Space' : key,
    windowsVirtualKeyCode: key === 'Tab' ? 9 : key === 'Enter' ? 13 : key === 'Escape' ? 27 : key.charCodeAt(0),
    modifiers,
  })
  await tab.send('Input.dispatchKeyEvent', {
    type: 'keyUp',
    key,
    code: key === ' ' ? 'Space' : key,
    windowsVirtualKeyCode: key === 'Tab' ? 9 : key === 'Enter' ? 13 : key === 'Escape' ? 27 : key.charCodeAt(0),
    modifiers,
  })
  await sleep(100)
}

async function screenshot(tab, name) {
  const result = await tab.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  await writeFile(resolve(evidenceDir, `${name}.png`), Buffer.from(result.data, 'base64'))
}

async function main() {
  await mkdir(evidenceDir, { recursive: true })

  const preview = spawnNpm(['run', 'preview', '--', '--host', '127.0.0.1', '--port', String(previewPort)])
  const userDataDir = resolve(tmpdir(), `datapilot-cdp-${Date.now()}`)
  const chrome = spawnProcess(findChromePath(), [
    '--headless=new',
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ], { cwd: root })

  const failures = []
  let tab

  try {
    await waitForHttp(`${baseUrl}/`)
    tab = await createBrowserTab(chrome)
    const browserErrors = []
    tab.events.set('Runtime.exceptionThrown', [
      (params) => browserErrors.push(params.exceptionDetails?.text || 'Runtime exception'),
    ])
    tab.events.set('Log.entryAdded', [
      (params) => {
        if (params.entry?.level === 'error') browserErrors.push(params.entry.text)
      },
    ])

    const viewportChecks = []
    for (const width of [320, 375, 768, 1024, 1440]) {
      await navigate(tab, '/', width, 900)
      viewportChecks.push(await evaluate(tab, `(() => ({
        width: ${width},
        noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        shellScrollable: document.querySelector('.marketing-shell').scrollHeight > document.querySelector('.marketing-shell').clientHeight,
        shellScrollMoves: (() => {
          const shell = document.querySelector('.marketing-shell');
          shell.scrollTop = 0;
          shell.scrollTop = 420;
          const moved = shell.scrollTop > 0;
          shell.scrollTop = 0;
          return moved;
        })(),
        headerVisible: !!document.querySelector('.marketing-header')?.getBoundingClientRect().height,
        footerVisible: !!document.querySelector('.marketing-footer')?.getBoundingClientRect().height,
        readableHero: getComputedStyle(document.querySelector('.premium-hero-copy p')).fontSize,
        activeNav: document.querySelector('.marketing-nav-link.is-active')?.textContent?.trim() || null
      }))()`))
    }

    await navigate(tab, '/', 1440, 900)
    const homepageState = await evaluate(tab, `(() => ({
      hero: document.body.textContent.includes('Stop Fighting Spreadsheets. Start Talking To Your Data.'),
      primaryCta: !!document.querySelector('a[href="/signup"]'),
      watchDemo: !!document.querySelector('a[href="#product-demo"]'),
      demo: !!document.querySelector('.product-preview'),
      problems: document.querySelectorAll('.problem-card').length,
      timeline: document.querySelectorAll('.timeline-step').length,
      outcomes: document.querySelectorAll('.outcome-card').length,
      industries: document.querySelectorAll('.industry-card').length,
      pricing: document.querySelectorAll('.pricing-card').length,
      faq: document.querySelectorAll('.faq-item').length,
      paidPlansDisabled: Array.from(document.querySelectorAll('.pricing-card button[disabled]')).length
    }))()`)
    assert.equal(homepageState.hero, true)
    assert.equal(homepageState.primaryCta, true)
    assert.equal(homepageState.watchDemo, true)
    assert.equal(homepageState.demo, true)
    assert.ok(homepageState.problems >= 6)
    assert.equal(homepageState.timeline, 4)
    assert.ok(homepageState.outcomes >= 6)
    assert.ok(homepageState.industries >= 11)
    assert.equal(homepageState.pricing, 4)
    assert.ok(homepageState.faq >= 7)
    assert.equal(homepageState.paidPlansDisabled, 3)

    for (const check of viewportChecks) {
      assert.equal(check.noHorizontalOverflow, true, `horizontal overflow at ${check.width}px`)
      assert.equal(check.shellScrollable, true, `marketing shell is not scrollable at ${check.width}px`)
      assert.equal(check.shellScrollMoves, true, `marketing shell scrollTop does not move at ${check.width}px`)
      assert.equal(check.headerVisible, true, `header missing at ${check.width}px`)
      assert.equal(check.footerVisible, true, `footer missing at ${check.width}px`)
      assert.ok(parseFloat(check.readableHero) >= 16, `hero text too small at ${check.width}px`)
    }

    for (const route of publicRoutes) {
      await navigate(tab, route)
      const routeState = await evaluate(tab, `(() => ({
        heading: document.querySelector('h1')?.textContent?.trim(),
        hasMain: !!document.querySelector('#main-content'),
        title: document.title,
        canonical: document.querySelector('link[rel="canonical"]')?.href,
        ogImage: document.querySelector('meta[property="og:image"]')?.content,
        robots: document.querySelector('meta[name="robots"]')?.content,
        noOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
      }))()`)
      assert.ok(routeState.heading, `${route} missing h1`)
      assert.equal(routeState.hasMain, true, `${route} missing main region`)
      assert.match(routeState.canonical, /^http:\/\/localhost:5173|^http:\/\/127\.0\.0\.1:4173|^http:\/\/localhost:5173/)
      assert.match(routeState.ogImage, /\/assets\/og-image\.png$/)
      assert.equal(routeState.robots, 'index, follow')
      assert.equal(routeState.noOverflow, true, `${route} has horizontal overflow`)
    }

    for (const [name, path, width, height] of screenshotTargets) {
      await navigate(tab, path, width, height)
      await screenshot(tab, name)
    }

    await navigate(tab, '/', 375, 812)
    await evaluate(tab, `document.querySelector('[aria-label="Open navigation"]').focus()`)
    await press(tab, 'Enter')
    if (await evaluate(tab, `document.querySelector('[aria-label="Open navigation"]')?.getAttribute('aria-expanded')`) !== 'true') {
      await press(tab, ' ')
    }
    const openState = await evaluate(tab, `(() => ({
      expanded: document.querySelector('[aria-label="Open navigation"]')?.getAttribute('aria-expanded'),
      panelVisible: !!document.querySelector('#mobile-navigation'),
      bodyLocked: document.body.style.overflow === 'hidden',
      focusedInside: document.querySelector('#mobile-navigation')?.contains(document.activeElement)
    }))()`)
    assert.equal(openState.expanded, 'true')
    assert.equal(openState.panelVisible, true)
    assert.equal(openState.bodyLocked, true)
    assert.equal(openState.focusedInside, true)
    await screenshot(tab, 'mobile-navigation-open')

    await evaluate(tab, `(() => {
      const items = Array.from(document.querySelectorAll('#mobile-navigation a, #mobile-navigation button'));
      items.at(-1).focus();
    })()`)
    await press(tab, 'Tab')
    const trappedFocus = await evaluate(tab, `document.querySelector('#mobile-navigation')?.contains(document.activeElement)`)
    assert.equal(trappedFocus, true)

    await press(tab, 'Escape')
    const closeState = await evaluate(tab, `(() => ({
      expanded: document.querySelector('[aria-label="Open navigation"]')?.getAttribute('aria-expanded'),
      panelVisible: !!document.querySelector('#mobile-navigation'),
      focusReturned: document.activeElement === document.querySelector('[aria-label="Open navigation"]'),
      bodyUnlocked: document.body.style.overflow !== 'hidden'
    }))()`)
    assert.equal(closeState.expanded, 'false')
    assert.equal(closeState.panelVisible, false)
    assert.equal(closeState.focusReturned, true)
    assert.equal(closeState.bodyUnlocked, true)

    await navigate(tab, '/', 1024, 768)
    await press(tab, 'Tab')
    const skipFocused = await evaluate(tab, `document.activeElement?.textContent?.trim()`)
    assert.equal(skipFocused, 'Skip to content')
    await press(tab, 'Enter')
    const skipTarget = await evaluate(tab, `document.activeElement?.id`)
    assert.equal(skipTarget, 'main-content')

    await navigate(tab, '/features', 1024, 768)
    const activeFeature = await evaluate(tab, `document.querySelector('.marketing-nav-link.is-active')?.textContent?.trim()`)
    assert.equal(activeFeature, 'Features')

    await navigate(tab, '/', 1024, 768)
    await evaluate(tab, `document.querySelector('a[href="/login"]').click()`)
    await sleep(400)
    assert.match(await evaluate(tab, `location.pathname`), /^\/login/)
    await navigate(tab, '/', 1024, 768)
    await evaluate(tab, `document.querySelector('a[href="/signup"]').click()`)
    await sleep(400)
    assert.match(await evaluate(tab, `location.pathname`), /^\/signup/)

    assert.deepEqual(browserErrors, [])
    browserErrors.length = 0

    await navigate(tab, '/app/analyze', 1024, 768)
    await sleep(900)
    const protectedState = await evaluate(tab, `({ path: location.pathname, signInVisible: document.body.textContent.includes('Welcome back') || document.body.textContent.includes('Sign In') })`)
    assert.equal(protectedState.path, '/login')
    assert.equal(protectedState.signInVisible, true)

    await navigate(tab, '/missing-route', 1024, 768)
    const notFoundState = await evaluate(tab, `document.body.textContent.includes('Page not found') && !!document.querySelector('a[href="/"]')`)
    assert.equal(notFoundState, true)

    await tab.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    })
    const reducedMotion = await evaluate(tab, `matchMedia('(prefers-reduced-motion: reduce)').matches`)
    assert.equal(reducedMotion, true)

    await writeFile(
      resolve(evidenceDir, 'browser-verification.json'),
      JSON.stringify({
        baseUrl,
        screenshots: ['mobile-navigation-open', ...screenshotTargets.map(([name]) => name)].map((name) => `${name}.png`),
        viewportChecks,
        publicRoutesChecked: publicRoutes,
        homepageChecks: homepageState,
        keyboardChecks: [
          'skip link focus and activation',
          'mobile menu keyboard open',
          'focus remains inside mobile menu',
          'escape closes mobile menu',
          'focus returns to trigger',
          'desktop active nav state',
          'signin and try free links navigate',
          'protected app route redirects to login',
        ],
      }, null, 2),
      'utf8'
    )
  } catch (error) {
    failures.push(error)
  } finally {
    tab?.close()
    killProcessTree(chrome)
    killProcessTree(preview)
    await sleep(500)
    await rm(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 }).catch(() => {})
  }

  if (failures.length) {
    throw failures[0]
  }
}

await main()
console.log(`Browser verification passed. Evidence written to ${evidenceDir}`)
process.exit(0)
