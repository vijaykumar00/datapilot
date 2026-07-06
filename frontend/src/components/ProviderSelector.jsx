import { useState, useRef, useEffect } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

const PROVIDERS = [
  {
    id: 'gemini',
    label: 'Gemini',
    icon: '✨',
    color: '#4285f4',
    gradient: 'linear-gradient(135deg, #4285f4, #34a853)',
    free: true,
    hint: 'Free tier · aistudio.google.com/apikey',
    keyRequired: true,
    keyPlaceholder: 'AIza...',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    icon: '🤖',
    color: '#10a37f',
    gradient: 'linear-gradient(135deg, #10a37f, #1a7f64)',
    free: false,
    hint: 'Paid · platform.openai.com/api-keys',
    keyRequired: true,
    keyPlaceholder: 'sk-...',
  },
  {
    id: 'claude',
    label: 'Claude',
    icon: '🎭',
    color: '#d97706',
    gradient: 'linear-gradient(135deg, #d97706, #b45309)',
    free: false,
    hint: 'Paid · console.anthropic.com',
    keyRequired: true,
    keyPlaceholder: 'sk-ant-...',
  },
  {
    id: 'ollama',
    label: 'Ollama',
    icon: '🦙',
    color: '#6366f1',
    gradient: 'linear-gradient(135deg, #6366f1, #4f46e5)',
    free: true,
    hint: 'Local · ollama.ai',
    keyRequired: false,
    keyPlaceholder: '',
  },
]

export default function ProviderSelector() {
  const { provider, providerOnline, switchProvider, checkProvider } = useDataPilot()
  const [open, setOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [switching, setSwitching] = useState(false)
  const [pendingId, setPendingId] = useState(null)
  const [error, setError] = useState('')
  const dropdownRef = useRef(null)

  const current = PROVIDERS.find(p => p.id === provider) || PROVIDERS[0]

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false)
        setPendingId(null)
        setApiKey('')
        setError('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSelect = (p) => {
    setError('')
    // Ollama: switch immediately, no key needed
    if (p.id === 'ollama') {
      doSwitch(p.id, null)
      return
    }
    // Same provider already online: just close
    if (p.id === provider && providerOnline) {
      setOpen(false)
      return
    }
    // Try switching immediately — backend may already have the key in .env
    // If it succeeds, great. If it fails (offline), then show key input.
    doSwitchOrPrompt(p.id)
  }

  const doSwitchOrPrompt = async (id) => {
    setSwitching(true)
    setError('')
    try {
      const result = await switchProvider(id, undefined)
      if (result?.success && result?.online) {
        // Success with server-configured key — done
        setOpen(false)
        setTimeout(() => checkProvider?.(), 800)
      } else if (result?.success && !result?.online) {
        // Switched but offline — backend has no key, ask user
        setPendingId(id)
        setApiKey('')
        setError('No API key configured. Please enter your key below.')
      } else {
        // Full failure — show key input
        setPendingId(id)
        setApiKey('')
      }
    } catch {
      // Backend offline
      setPendingId(id)
      setApiKey('')
      setError('Backend is offline. Start the server first, then enter your key.')
    } finally {
      setSwitching(false)
    }
  }


  const doSwitch = async (id, key) => {
    setSwitching(true)
    setError('')
    try {
      const result = await switchProvider(id, key || undefined)
      if (result?.success) {
        setPendingId(null)
        setApiKey('')
        setOpen(false)
        // Re-check status after switch
        setTimeout(() => checkProvider?.(), 800)
      } else if (result?.success === false && !key && id !== 'ollama') {
        // No key provided and switch returned failure
        setError('Please enter a valid API key.')
      } else {
        // Generic failure — likely backend is offline
        setError(
          result?.detail ||
          result?.message ||
          'Could not connect to backend. Make sure the server is running.'
        )
      }
    } catch (err) {
      setError('Backend is offline. Start the server and try again.')
    } finally {
      setSwitching(false)
    }
  }

  const handleConnect = () => {
    if (!pendingId) return
    if (!apiKey.trim()) {
      setError('Please paste your API key first.')
      return
    }
    doSwitch(pendingId, apiKey.trim())
  }

  const pendingProvider = PROVIDERS.find(p => p.id === pendingId)

  return (
    <div className="px-3 pb-2" ref={dropdownRef}>
      {/* Current provider badge — click to open */}
      <button
        id="provider-selector-btn"
        onClick={() => {
          setOpen(o => !o)
          if (open) { setPendingId(null); setApiKey(''); setError('') }
        }}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-xl glass-sm border border-white/8 hover:border-white/15 transition-all duration-200 group"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className="text-base">{current.icon}</span>
        <div className="flex-1 text-left">
          <div className="text-xs font-semibold text-slate-200">{current.label}</div>
          <div className="text-[10px]">
            {providerOnline
              ? <span className="text-emerald-400">● Connected</span>
              : <span className="text-red-400">● Offline</span>}
          </div>
        </div>
        <svg
          className={`w-3.5 h-3.5 text-slate-500 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="mt-1.5 rounded-xl glass border border-white/10 overflow-hidden animate-fade-in shadow-xl">
          <div className="px-3 py-2 border-b border-white/5">
            <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">AI Provider</p>
          </div>

          {/* Provider list */}
          {!pendingId && PROVIDERS.map(p => (
            <button
              key={p.id}
              id={`provider-opt-${p.id}`}
              onClick={() => handleSelect(p)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-white/5 transition-colors ${
                p.id === provider ? 'bg-white/5' : ''
              }`}
            >
              <span className="text-base w-6 text-center">{p.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-slate-200">{p.label}</span>
                  {p.free && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                      FREE
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-slate-600 truncate">{p.hint}</p>
              </div>
              {p.id === provider && (
                <svg className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/>
                </svg>
              )}
            </button>
          ))}

          {/* API key input for pending cloud provider */}
          {pendingId && pendingProvider && (
            <div className="p-3 space-y-2.5">
              {/* Back button */}
              <button
                onClick={() => { setPendingId(null); setApiKey(''); setError('') }}
                className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors mb-1"
              >
                ← Back
              </button>

              <div className="flex items-center gap-2 mb-2">
                <span className="text-xl">{pendingProvider.icon}</span>
                <div>
                  <p className="text-xs font-semibold text-slate-200">{pendingProvider.label}</p>
                  <p className="text-[10px] text-slate-500">{pendingProvider.hint}</p>
                </div>
              </div>

              <p className="text-[11px] text-slate-400">
                Paste your {pendingProvider.label} API key to connect:
              </p>

              <input
                id="provider-api-key-input"
                type="password"
                placeholder={pendingProvider.keyPlaceholder || 'Paste API key...'}
                value={apiKey}
                onChange={e => { setApiKey(e.target.value); setError('') }}
                onKeyDown={e => e.key === 'Enter' && handleConnect()}
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50 focus:ring-1 focus:ring-brand-500/20"
                autoFocus
              />

              {error && (
                <p className="text-[10px] text-red-400 px-1">{error}</p>
              )}

              <div className="flex gap-2">
                <button
                  id="provider-connect-btn"
                  onClick={handleConnect}
                  disabled={switching}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #4f46e5)', color: 'white' }}
                >
                  {switching ? 'Connecting...' : `Connect ${pendingProvider.label}`}
                </button>
                <button
                  onClick={() => { setPendingId(null); setApiKey(''); setError('') }}
                  className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-all"
                >
                  Cancel
                </button>
              </div>

              <p className="text-[9px] text-slate-600 text-center">
                Your key is sent directly to your backend — never stored in the browser.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
