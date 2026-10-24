import { apiUrl } from './apiConfig'
import { hasSession, refreshSession, sessionHeaders } from './authSession.js'

export class BillingApiError extends Error {
  constructor(message, status, payload = null) {
    super(message)
    this.name = 'BillingApiError'
    this.status = status
    this.payload = payload
  }
}

async function readJson(response) {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { detail: text }
  }
}

async function request(path, { method = 'GET', headers = {}, body, signal } = {}) {
  // Session cookies authenticate; sessionHeaders() adds the CSRF token for unsafe methods.
  const send = () => fetch(apiUrl(path), {
    method,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...sessionHeaders(method, headers),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  let response = await send()
  if (response.status === 401 && hasSession()) {
    // Access cookie expired: refresh through the HttpOnly refresh cookie and retry once.
    if (await refreshSession()) response = await send()
  }
  const payload = await readJson(response)
  if (!response.ok) {
    const detail = payload.detail
    const message = (typeof payload.error === 'string' && payload.error)
      || (typeof detail === 'string' && detail)
      || (detail && typeof detail.message === 'string' && detail.message)
      || 'Billing request failed.'
    throw new BillingApiError(message, response.status, payload)
  }
  return payload
}

export function createBillingClient(apiHeaders = () => ({})) {
  const authHeaders = () => apiHeaders()

  return {
    getPlans: (options = {}) => request('/billing/plans', options),
    getCurrent: (options = {}) => request('/billing/current', { ...options, headers: authHeaders() }),
    getStatus: (options = {}) => request('/billing/status', { ...options, headers: authHeaders() }),
    getUsage: (options = {}) => request('/billing/usage', { ...options, headers: authHeaders() }),
    getQuota: (options = {}) => request('/billing/quota', { ...options, headers: authHeaders() }),
    getFeatures: (options = {}) => request('/billing/features', { ...options, headers: authHeaders() }),
    createCheckout: (payload, options = {}) => request('/billing/checkout', {
      ...options,
      method: 'POST',
      headers: authHeaders(),
      body: payload,
    }),
    createPortal: (payload = {}, options = {}) => request('/billing/portal', {
      ...options,
      method: 'POST',
      headers: authHeaders(),
      body: payload,
    }),
  }
}

export function isSafeBillingRedirect(url) {
  try {
    const parsed = new URL(url, window.location.origin)
    if (parsed.protocol !== 'https:' && parsed.origin !== window.location.origin) return false
    return (
      parsed.hostname === window.location.hostname ||
      parsed.hostname === 'checkout.stripe.com' ||
      parsed.hostname.endsWith('.stripe.com')
    )
  } catch {
    return false
  }
}

export function centsToPrice(cents, interval = 'monthly') {
  if (cents === null || cents === undefined) return 'Contact sales'
  if (cents === 0) return '$0'
  const suffix = interval === 'annual' ? '/yr' : '/mo'
  return `$${Math.round(cents / 100).toLocaleString()}${suffix}`
}

export function formatLimit(value, unit = '') {
  if (value === null || value === undefined || value === -1) return 'Unlimited'
  if (unit === 'bytes') return formatBytes(value)
  return `${Number(value).toLocaleString()}${unit ? ` ${unit}` : ''}`
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || bytes === -1) return 'Unlimited'
  const value = Number(bytes)
  if (!Number.isFinite(value)) return 'Unknown'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value / 1024
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size >= 10 ? Math.round(size) : size.toFixed(1)} ${units[index]}`
}

export function friendlyBillingStatus(status) {
  const map = {
    free: 'Free plan',
    trialing: 'Trial active',
    active: 'Active',
    past_due: 'Payment past due',
    unpaid: 'Unpaid',
    canceled: 'Cancelled',
    cancelled: 'Cancelled',
    incomplete: 'Checkout incomplete',
    incomplete_expired: 'Checkout expired',
    expired: 'Trial expired',
  }
  return map[status] || 'Sync pending'
}

export function daysUntil(dateString) {
  if (!dateString) return null
  const target = new Date(dateString).getTime()
  if (Number.isNaN(target)) return null
  return Math.max(0, Math.ceil((target - Date.now()) / 86_400_000))
}

// ── Currencies and plan copy ────────────────────────────────────────────────

const CURRENCY_KEY = 'tallis_currency'

/** INR for visitors in India (by time zone), USD elsewhere; a manual choice is remembered. */
export function defaultCurrency() {
  try {
    const saved = localStorage.getItem(CURRENCY_KEY)
    if (saved === 'INR' || saved === 'USD') return saved
  } catch { /* storage blocked */ }
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  return tz === 'Asia/Kolkata' || tz === 'Asia/Calcutta' ? 'INR' : 'USD'
}

export function rememberCurrency(currency) {
  try { localStorage.setItem(CURRENCY_KEY, currency) } catch { /* storage blocked */ }
}

/** Price label from a plan's minor units (paise / cents). */
export function formatPlanPrice(plan, currency = 'USD', interval = 'monthly') {
  if (plan?.plan_id === 'enterprise') return 'Contact sales'
  const minor = plan?.prices?.[currency]?.[interval === 'annual' ? 'annual' : 'monthly']
    ?? (currency === 'USD' ? (interval === 'annual' ? plan?.annual_price_cents : plan?.monthly_price_cents) : null)
  if (minor === null || minor === undefined) return 'Contact sales'
  const symbol = currency === 'INR' ? '₹' : '$'
  if (minor === 0) return `${symbol}0`
  const amount = Math.round(minor / 100).toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US')
  return `${symbol}${amount}${interval === 'annual' ? '/yr' : '/mo'}`
}

const FEATURE_LINES = [
  ['can_export_pdf', 'Reports as PDF and Word'],
  ['can_forecast', 'Forecasts'],
  ['can_use_multiple_datasets', 'Questions across several files'],
  ['can_invite_members', 'Team roles and shared workspace'],
  ['can_access_priority_support', 'Priority support'],
]

/** What a plan includes, in the words customers use. */
export function planHighlights(plan) {
  const l = plan?.limits || {}
  const lines = ['Unlimited instant answers']
  const ai = l.query_count ?? l.ai_prompt_count
  lines.push(ai === null || ai === undefined || ai === -1 ? 'Unlimited AI questions' : `${Number(ai).toLocaleString()} AI questions a month`)
  lines.push(`${formatLimit(l.storage_bytes, 'bytes')} storage`)
  if (l.max_file_size_bytes) lines.push(`Files up to ${formatBytes(l.max_file_size_bytes)}`)
  if (l.max_pdf_pages) lines.push(`PDFs up to ${Number(l.max_pdf_pages).toLocaleString()} pages`)
  if (l.member_count && l.member_count !== 1) lines.push(`${formatLimit(l.member_count)} team members`)
  for (const [key, text] of FEATURE_LINES) if (plan?.features?.[key]) lines.push(text)
  return lines
}

export function createPaymentsClient() {
  return {
    getProviders: () => request('/billing/providers'),
    createRazorpaySubscription: (payload) => request('/billing/razorpay/subscription', { method: 'POST', body: payload }),
    verifyRazorpay: (payload) => request('/billing/razorpay/verify', { method: 'POST', body: payload }),
    cancelRazorpay: (payload = { at_cycle_end: true }) => request('/billing/razorpay/cancel', { method: 'POST', body: payload }),
  }
}
