import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

function read(path) {
  return readFileSync(new URL(path, import.meta.url), 'utf8')
}

test('billing client centralizes subscription API calls and keeps Stripe secrets out of the browser', () => {
  const client = read('../src/lib/billingClient.js')

  for (const endpoint of [
    '/billing/plans',
    '/billing/current',
    '/billing/status',
    '/billing/usage',
    '/billing/quota',
    '/billing/features',
    '/billing/checkout',
    '/billing/portal',
  ]) {
    assert.match(client, new RegExp(endpoint.replaceAll('/', '\\/')))
  }

  assert.match(client, /createCheckout/)
  assert.match(client, /createPortal/)
  assert.match(client, /isSafeBillingRedirect/)
  assert.doesNotMatch(client, /sk_live|sk_test|whsec|STRIPE_SECRET|WEBHOOK_SECRET/)
  assert.doesNotMatch(client, /stripe\.checkout\.Session/)
})

test('billing page renders backend subscription state, quotas, checkout, portal, and return refresh UX', () => {
  const billing = read('../src/components/BillingPortal.jsx')

  for (const text of [
    'Plan and usage',
    'Workspace limits',
    'Compare available plans',
    'Processing subscription update',
    'Checkout cancelled',
    'Manage billing',
    'createCheckout',
    'createPortal',
    'portal_available',
    'cancel_at_period_end',
    'payment_status',
    'remaining_quota',
    'role="progressbar"',
    'aria-valuetext',
  ]) {
    assert.match(billing, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }

  assert.doesNotMatch(billing, /\/user\/usage/)
  assert.doesNotMatch(billing, /stripe\.com\/v1/)
  assert.doesNotMatch(billing, /localStorage\.setItem\([^)]*subscription/i)
})

test('pricing page uses backend plans and secure server-generated checkout or portal URLs', () => {
  const pricing = read('../src/pages/marketing/PricingPage.jsx')
  const marketing = read('../src/data/marketing.js')
  const home = read('../src/pages/marketing/HomePage.jsx')

  assert.match(pricing, /client\.getPlans/)
  assert.match(pricing, /client\.getCurrent/)
  assert.match(pricing, /client\.createCheckout/)
  assert.match(pricing, /client\.createPortal/)
  assert.match(pricing, /isSafeBillingRedirect/)
  assert.match(pricing, /Sign up to choose/)
  assert.match(pricing, /Current plan/)
  assert.match(pricing, /Contact sales/)
  assert.doesNotMatch(pricing, /price_[A-Za-z0-9]{8,}/)
  assert.doesNotMatch(pricing, /sk_live|sk_test|whsec/)
  assert.doesNotMatch(marketing, /checkout are intentionally out of scope/i)
  assert.doesNotMatch(home, /Coming Soon|paid plans are ready|not enabled in this sprint/i)
})

test('billing styles include responsive, accessible, non-color-only usage states', () => {
  const styles = read('../src/index.css')

  for (const selector of [
    '.billing-shell',
    '.billing-current-grid',
    '.billing-usage-grid',
    '.billing-progress',
    '.billing-usage-row-warning',
    '.billing-usage-row-danger',
    '.billing-plan-grid',
    '.pricing-plan-grid',
    '@media (max-width: 760px)',
  ]) {
    assert.match(styles, new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})
