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
  assert.match(header, /to="\/try-free"/)
  assert.match(mobile, /to="\/try-free"/)
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

  assert.match(app, /path="\/app" element={<RouteGuard><AppShell \/><\/RouteGuard>}/)
  // Pages consolidated for the MVP keep their old URLs working.
  for (const old of ['dashboard', 'report', 'presentation', 'templates', 'history']) {
    assert.match(app, new RegExp(`path="${old}" element={<Navigate to=`))
  }
  assert.match(app, /path="\/try-free" element={<GuestModeTrigger \/>}/)
  assert.match(app, /path="\/auth\/oauth\/google\/callback" element={<OAuthCallback provider="google" \/>}/)
  assert.match(app, /path="\/auth\/oauth\/microsoft\/callback" element={<OAuthCallback provider="microsoft" \/>}/)
  assert.match(app, /path="\*" element={<NotFoundPage \/>}/)
  assert.doesNotMatch(app, /path="\*" element={<Navigate to="\/" replace \/>}/)
})

test('SEO foundation sets canonical, OG, Twitter, and noindex metadata', () => {
  const seo = read('../src/components/marketing/SEO.jsx')
  const app = read('../src/App.jsx')
  const shell = read('../src/components/shell/AppShell.jsx')

  assert.match(seo, /link\[rel="canonical"\]/)
  assert.match(seo, /og:title/)
  assert.match(seo, /og:description/)
  assert.match(seo, /og:image/)
  assert.match(seo, /twitter:card/)
  assert.match(seo, /noindex, nofollow/)
  assert.match(shell, /canonicalPath="\/app"[\s\S]*noindex/)
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

test('homepage leads with the product and keeps the essential sections', () => {
  const home = read('../src/pages/marketing/HomePage.jsx')

  for (const text of [
    'Stop fighting spreadsheets. Start talking to your data.',
    'Animated Tallis product walkthrough',
    'What were our highest profit products?',
    'Upload. Ask. Understand. Share.',
    'What you can do with Tallis',
    'Trust and security',
    'Pricing preview',
    'FAQ',
    'Ready to stop spending hours inside Excel?',
  ]) {
    assert.match(home, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
  // No claims about features the MVP does not expose.
  assert.doesNotMatch(home, /Ollama|own API key|provider keys/i)
})
test('marketing path does not statically import Plotly chart renderer', () => {
  const app = read('../src/App.jsx')
  const chat = read('../src/components/ChatWindow.jsx')

  assert.doesNotMatch(app, /import ChartRenderer from/)
  assert.doesNotMatch(chat, /import ChartRenderer from/)
  assert.doesNotMatch(app, /ChartRenderer/)
  assert.match(chat, /lazy\(\(\) => import\('\.\/ChartRenderer'\)\)/)
})

test('workspace home answers what to do, what data exists and what was recent', () => {
  const dashboard = read('../src/components/DashboardHome.jsx')

  for (const text of [
    'Upload data',
    'Ask AI',
    'Ask about your data',
    'Your data',
    'Recent reports',
    'Recent conversations',
    'Usage',
    'GettingStarted',
    'No reports yet',
    'No conversations yet',
  ]) {
    assert.match(dashboard, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('getting-started checklist persists progress and dismissal on the home page', () => {
  const assistant = read('../src/components/OnboardingAssistant.jsx')
  const dashboard = read('../src/components/DashboardHome.jsx')

  for (const text of [
    'dp_onboarding_state_v1',
    'Hide getting started',
    'completedCelebrated',
    'dismissed',
    'Your guest work was moved into your new account',
    'Getting started',
  ]) {
    assert.match(assistant, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }

  // The checklist lives on the home page instead of floating over the chat composer.
  assert.match(dashboard, /<GettingStarted \/>/)
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
  assert.match(upload, /Drag files here/)
})

test('guest conversion and accessibility affordances are present', () => {
  const auth = read('../src/components/AuthModal.jsx')
  const styles = read('../src/index.css') + read('../src/styles/tokens.css') + read('../src/styles/base.css')
  const marketingData = read('../src/data/marketing.js')
  const header = read('../src/components/marketing/MarketingHeader.jsx')
  const home = read('../src/pages/marketing/HomePage.jsx')

  assert.match(auth, /dp_guest_converted_success/)
  assert.match(auth, /Your guest work is saved/)
  assert.match(auth, /with Google/)
  assert.match(auth, /with Microsoft/)
  // Social sign-in buttons only render when the server reports the provider as configured.
  assert.match(auth, /\/auth\/oauth\/providers/)
  assert.match(auth, /htmlFor=/)
  assert.match(header, /to="\/try-free"/)
  assert.match(home, /Try Tallis in guest mode without creating an account/)
  assert.match(marketingData, /ctaTo: '\/try-free'/)
  assert.match(styles, /:focus-visible/)
  assert.match(styles, /prefers-reduced-motion: reduce/)
  assert.match(styles, /max-width: 640px/)
})

test('design system defines semantic light and dark tokens and shared focus behaviour', () => {
  const tokens = read('../src/styles/tokens.css')
  const base = read('../src/styles/base.css')
  const tailwind = read('../tailwind.config.js')

  for (const token of ['--c-bg', '--c-surface', '--c-fg', '--c-muted', '--c-line', '--c-primary', '--c-success',
    '--c-warning', '--c-danger', '--c-focus', '--radius-control', '--radius-card', '--motion-fast', '--font-sans']) {
    assert.match(tokens, new RegExp(token))
  }
  // A deliberate dark theme, not an inversion.
  assert.match(tokens, /\.dark\s*{/)
  assert.match(base, /--focus-ring/)
  assert.match(base, /:focus-visible/)
  assert.match(tailwind, /darkMode: 'class'/)
  assert.match(tailwind, /rgb\(var\(--c-\$\{name\}\) \/ <alpha-value>\)/)
})

test('toast system uses token colors and accessible dismissal', () => {
  const toast = read('../src/components/ToastContainer.jsx')

  assert.match(toast, /text-success/)
  assert.match(toast, /text-danger/)
  assert.match(toast, /role=\{type === 'error' \? 'alert' : 'status'\}/)
  assert.match(toast, /aria-label="Dismiss notification"/)
  assert.match(toast, /aria-live="polite"/)
  assert.doesNotMatch(toast, /#[0-9a-fA-F]{6}/)
})

test('Sprint 3.5 browser verification records design consistency and 1280px responsive checks', () => {
  const browser = read('./browser-verify.mjs')

  assert.match(browser, /rc-2/)
  assert.match(browser, /1280/)
  assert.match(browser, /consistencyChecks/)
  assert.match(browser, /radiusButton/)
  assert.match(browser, /focusVisibleRule/)
  assert.match(browser, /reducedMotionRule/)
})

test('routes are code-split: marketing and workspace views are lazy-loaded', () => {
  const app = read('../src/App.jsx')
  const shell = read('../src/components/shell/AppShell.jsx')
  for (const name of ['HomePage', 'PricingPage', 'NotFoundPage', 'AppShell', 'AuthModal', 'ChatWindow', 'SpreadsheetPage',
    'BillingPortal', 'SettingsLayout', 'DashboardHome', 'ReportsPage', 'SavedPage', 'DatasetManager']) {
    assert.doesNotMatch(app, new RegExp(`^import ${name} from`, 'm'), name)
    assert.match(app, new RegExp(`const ${name} = lazy\\(`), name)
  }
  assert.doesNotMatch(app, /^import ReactMarkdown from/m)
  assert.doesNotMatch(app, /^import .* from '\.\/hooks\/useDataPilot'/m)
  assert.doesNotMatch(app, /^import .* from '\.\/components\/LegalPages'/m)
  // Every lazy view renders inside a Suspense boundary.
  assert.match(app, /<Suspense fallback={<ViewFallback \/>}>\s*<Routes>/)
  assert.match(shell, /<Suspense fallback={<PageSkeleton \/>}>\s*<Outlet \/>/)
})
