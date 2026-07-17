const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8001').replace(/\/+$/, '')

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
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new BillingApiError(payload.detail || payload.error || 'Billing request failed.', response.status, payload)
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
