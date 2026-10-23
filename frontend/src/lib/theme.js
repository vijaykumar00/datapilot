import { useCallback, useEffect, useSyncExternalStore } from 'react'

// Theme preference: 'light' | 'dark' | 'system'.  Persisted in localStorage and
// applied as the `dark` class on <html> (public/theme-init.js does the first paint).
const KEY = 'dp_theme'
const listeners = new Set()
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null

function read() {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' ? value : 'system'
  } catch {
    return 'system'
  }
}

export function resolvedTheme(pref = read()) {
  if (pref === 'system') return media?.matches ? 'dark' : 'light'
  return pref
}

function apply(pref) {
  const dark = resolvedTheme(pref) === 'dark'
  document.documentElement.classList.toggle('dark', dark)
}

export function setThemePreference(pref) {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  } catch { /* private mode: still applies for this page */ }
  apply(pref)
  listeners.forEach((fn) => fn())
}

function subscribe(fn) {
  listeners.add(fn)
  const onMedia = () => { if (read() === 'system') { apply('system'); fn() } }
  media?.addEventListener?.('change', onMedia)
  return () => { listeners.delete(fn); media?.removeEventListener?.('change', onMedia) }
}

export function useTheme() {
  const preference = useSyncExternalStore(subscribe, read, () => 'system')
  const theme = useSyncExternalStore(subscribe, () => resolvedTheme(read()), () => 'light')
  useEffect(() => { apply(preference) }, [preference])
  const setPreference = useCallback((p) => setThemePreference(p), [])
  return { preference, theme, setPreference }
}
