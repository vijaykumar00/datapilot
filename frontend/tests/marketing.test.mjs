import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  legalRouteMetadata,
  marketingNavItems,
  publicRouteMetadata,
  publicSitemapRoutes,
} from '../src/data/marketing.js'

const requiredPublicRoutes = [
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

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('all Sprint 3.1 public routes have metadata and sitemap entries', () => {
  for (const route of requiredPublicRoutes) {
    const metadata = publicRouteMetadata[route] || legalRouteMetadata[route]
    assert.ok(metadata, `${route} is missing route metadata`)
    assert.ok(metadata.title?.length > 2, `${route} needs a title`)
    assert.ok(metadata.description?.length > 48, `${route} needs a useful description`)
    assert.ok(publicSitemapRoutes.includes(route), `${route} is missing from sitemap route data`)
  }
})

test('marketing navigation exposes accessible public links and auth CTAs', () => {
  const header = read('../src/components/marketing/MarketingHeader.jsx')
  const mobile = read('../src/components/marketing/MobileNavigation.jsx')

  assert.deepEqual(
    marketingNavItems.map((item) => item.path),
    ['/', '/features', '/use-cases', '/security', '/pricing', '/docs', '/about', '/contact']
  )
  assert.match(header, /aria-expanded/)
  assert.match(header, /aria-controls="mobile-navigation"/)
  assert.match(mobile, /Escape/)
  assert.match(mobile, /document.body.style.overflow = 'hidden'/)
  assert.match(mobile, /aria-label="Mobile navigation"/)
  assert.match(header, /to="\/login"/)
  assert.match(header, /to="\/signup"/)
})

test('router keeps app protected, registers public routes, and renders public 404', () => {
  const app = read('../src/App.jsx')

  for (const route of requiredPublicRoutes) {
    if (route === '/') {
      assert.match(app, /path="\/" element={<HomePage \/>}/)
    } else {
      assert.match(app, new RegExp(`path="${route.replaceAll('/', '\\/')}"`))
    }
  }

  assert.match(app, /path="\/app" element={<RouteGuard><AppLayout \/><\/RouteGuard>}/)
  assert.match(app, /path="\*" element={<NotFoundPage \/>}/)
  assert.doesNotMatch(app, /path="\*" element={<Navigate to="\/" replace \/>}/)
})

test('SEO foundation sets canonical, OG, Twitter, and noindex metadata', () => {
  const seo = read('../src/components/marketing/SEO.jsx')
  const app = read('../src/App.jsx')

  assert.match(seo, /link\[rel="canonical"\]/)
  assert.match(seo, /og:title/)
  assert.match(seo, /og:description/)
  assert.match(seo, /og:image/)
  assert.match(seo, /twitter:card/)
  assert.match(seo, /noindex, nofollow/)
  assert.match(app, /canonicalPath="\/app"[\s\S]*noindex/)
  assert.match(app, /canonicalPath=.*\/login/)
})

test('public assets exist and avoid emoji favicon branding', () => {
  const index = read('../index.html')
  const robots = read('../public/robots.txt')

  assert.match(index, /href="\/favicon\.svg"/)
  assert.doesNotMatch(index, /data:image\/svg\+xml/)
  assert.match(robots, /Disallow: \/app\//)
  assert.ok(existsSync(new URL('../public/assets/logo-mark.svg', import.meta.url)))
  assert.ok(existsSync(new URL('../public/assets/logo-horizontal.svg', import.meta.url)))
  assert.ok(existsSync(new URL('../public/assets/og-image.png', import.meta.url)))
  assert.ok(existsSync(new URL('../public/assets/og-image.README.md', import.meta.url)))
})

test('Open Graph asset is the approved beta image size and public routes reference it', () => {
  const png = readFileSync(new URL('../public/assets/og-image.png', import.meta.url))
  const width = png.readUInt32BE(16)
  const height = png.readUInt32BE(20)
  const seo = read('../src/components/marketing/SEO.jsx')
  const marketingData = read('../src/data/marketing.js')

  assert.equal(width, 1200)
  assert.equal(height, 630)
  assert.match(marketingData, /ogImage: '\/assets\/og-image\.png'/)
  assert.match(seo, /siteConfig\.ogImage/)
})

test('Sprint 3.2 homepage includes premium product experience sections', () => {
  const home = read('../src/pages/marketing/HomePage.jsx')

  for (const text of [
    'Stop Fighting Spreadsheets. Start Talking To Your Data.',
    'Animated DataPilot product walkthrough',
    'What were our highest profit products?',
    'Business problems',
    'Upload. Ask. Understand. Share.',
    'Built around the result, not the menu item',
    'Replace workbook busywork with a focused answer loop',
    'Industry use cases',
    'A clearer path than manual spreadsheet analysis',
    'Trust and security',
    'Pricing preview',
    'FAQ',
    'Ready To Stop Spending Hours Inside Excel?',
  ]) {
    assert.match(home, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('marketing path does not statically import Plotly chart renderer', () => {
  const app = read('../src/App.jsx')
  const chat = read('../src/components/ChatWindow.jsx')

  assert.doesNotMatch(app, /import ChartRenderer from/)
  assert.doesNotMatch(chat, /import ChartRenderer from/)
  assert.match(app, /lazy\(\(\) => import\('\.\/components\/ChartRenderer'\)\)/)
  assert.match(chat, /lazy\(\(\) => import\('\.\/ChartRenderer'\)\)/)
})

test('Sprint 3.3 premium dashboard includes required workspace sections', () => {
  const dashboard = read('../src/components/DashboardHome.jsx')

  for (const text of [
    'Upload Dataset',
    'Try Demo Dataset',
    'Continue Previous Analysis',
    'Recent Datasets',
    'Recent Reports',
    'Recent Conversations',
    'Suggested Questions',
    'Usage',
    'Onboarding Progress',
    'Premium Templates',
    'No Dataset',
    'No Reports',
    'No Chat',
    'Sales',
    'Finance',
    'Inventory',
    'HR',
    'Marketing',
    'Construction',
    'Healthcare',
    'Retail',
  ]) {
    assert.match(dashboard, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('Sprint 3.4 guided onboarding persists progress, skip, resume, and completion states', () => {
  const assistant = read('../src/components/OnboardingAssistant.jsx')
  const app = read('../src/App.jsx')

  for (const text of [
    'dp_onboarding_state_v1',
    'Skip onboarding',
    'Resume onboarding',
    'Resume later',
    'Onboarding complete',
    'Guest converted to account',
    'Success: you uploaded data',
    'aria-label="Guided onboarding"',
  ]) {
    assert.match(assistant, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }

  assert.match(app, /<OnboardingAssistant \/>/)
})

test('Sprint 3.4 starter prompts cover target dataset categories', () => {
  const assistant = read('../src/components/OnboardingAssistant.jsx')

  for (const text of [
    'sales',
    'finance',
    'hr',
    'marketing',
    'inventory',
    'healthcare',
    'construction',
    'operations',
    'Show monthly sales',
    'Find budget variance',
    'Show hiring bottlenecks',
    'Which campaigns convert best?',
    'Find low stock items',
    'Find overbooked clinics',
    'Which projects are over budget?',
    'Find process bottlenecks',
  ]) {
    assert.match(assistant, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('Sprint 3.4 onboarding route and chat prompt handoff support activation flow', () => {
  const flow = read('../src/components/OnboardingFlow.jsx')
  const chat = read('../src/components/ChatWindow.jsx')
  const upload = read('../src/components/FileUploader.jsx')

  for (const text of [
    'First analysis setup',
    'Start with upload',
    'Skip for now',
    'dp_usecase_preference',
    'Upload a spreadsheet',
    'Ask a starter question',
    'Generate a chart',
    'Create a report',
    'Save the report',
  ]) {
    assert.match(flow, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }

  assert.match(chat, /suggestedPrompt/)
  assert.match(chat, /inputRef\.current\?\.focus/)
  assert.match(upload, /Upload your first spreadsheet/)
})

test('Sprint 3.4 guest conversion and accessibility affordances are present', () => {
  const auth = read('../src/components/AuthModal.jsx')
  const styles = read('../src/index.css')

  assert.match(auth, /dp_guest_converted_success/)
  assert.match(auth, /Your guest work is preserved/)
  assert.match(styles, /\.onboarding-assistant-toggle:focus-visible/)
  assert.match(styles, /prefers-reduced-motion: reduce/)
  assert.match(styles, /max-width: 640px/)
})

test('Sprint 3.5 polish layer standardizes shared design tokens and focus behavior', () => {
  const styles = read('../src/index.css')

  for (const token of [
    '--space-1',
    '--space-2',
    '--space-3',
    '--space-4',
    '--space-6',
    '--radius-pill',
    '--motion-fast',
    '--motion-base',
    '--focus-ring',
    'Sprint 3.5 product polish',
    ':focus-visible',
  ]) {
    assert.match(styles, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }

  assert.match(styles, /\.auth-modal,\s*\n\.onboarding-panel,\s*\n\.user-dropdown/)
  assert.match(styles, /\.toast-container/)
  assert.match(styles, /max-width: 640px/)
})

test('Sprint 3.5 toast system uses token colors and accessible dismissal', () => {
  const toast = read('../src/components/ToastContainer.jsx')

  assert.match(toast, /var\(--success\)/)
  assert.match(toast, /var\(--error\)/)
  assert.match(toast, /role=\{toastType === 'error' \? 'alert' : 'status'\}/)
  assert.match(toast, /aria-label="Dismiss notification"/)
  assert.match(toast, /tabIndex=\{0\}/)
  assert.doesNotMatch(toast, /#[0-9a-fA-F]{6}/)
})

test('Sprint 3.5 browser verification records design consistency and 1280px responsive checks', () => {
  const browser = read('./browser-verify.mjs')

  assert.match(browser, /sprint-3-5/)
  assert.match(browser, /1280/)
  assert.match(browser, /consistencyChecks/)
  assert.match(browser, /radiusButton/)
  assert.match(browser, /focusVisibleRule/)
  assert.match(browser, /reducedMotionRule/)
})
