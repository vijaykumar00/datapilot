const DEFAULT_API_BASE = '/api'

function stripTrailingSlash(value) {
  return value.replace(/\/+$/, '')
}

function isLoopbackOrigin(value) {
  try {
    const url = new URL(value)
    return ['localhost', '127.0.0.1', '::1'].includes(url.hostname)
  } catch {
    return false
  }
}

export function getApiBase(env = import.meta.env) {
  const configured = String(env.VITE_API_URL || DEFAULT_API_BASE).trim()
  const normalized = configured === '/' ? '' : stripTrailingSlash(configured)

  if (
    env.PROD &&
    isLoopbackOrigin(normalized) &&
    env.VITE_ALLOW_LOCAL_API_IN_PRODUCTION !== 'true'
  ) {
    throw new Error(
      'Invalid production API configuration: VITE_API_URL must not point to a loopback host. Use /api or a deployed HTTPS API origin.'
    )
  }

  return normalized
}

export const API_BASE = getApiBase()

export function apiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}
