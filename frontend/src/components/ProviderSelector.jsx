import { useState } from 'react'
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
  },
  {
    id: 'openai',
    label: 'OpenAI',
    icon: '🤖',
    color: '#10a37f',
    gradient: 'linear-gradient(135deg, #10a37f, #1a7f64)',
    free: false,
    hint: 'Paid · platform.openai.com/api-keys',
  },
  {
    id: 'claude',
    label: 'Claude',
    icon: '🎭',
    color: '#d97706',
    gradient: 'linear-gradient(135deg, #d97706, #b45309)',
    free: false,
    hint: 'Paid · console.anthropic.com',
  },
  {
    id: 'ollama',
    label: 'Ollama',
    icon: '🦙',
    color: '#6366f1',
    gradient: 'linear-gradient(135deg, #6366f1, #4f46e5)',
    free: true,
    hint: 'Local · ollama.ai',
  },
]

export default function ProviderSelector() {
  const { provider, providerOnline, switchProvider } = useDataPilot()
  const [open, setOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [switching, setSwitching] = useState(false)
  const [pendingId, setPendingId] = useState(null)

  const current = PROVIDERS.find(p => p.id === provider) || PROVIDERS[0]
  const needsKey = pendingId && ['gemini', 'openai', 'claude'].includes(pendingId)

  const handleSelect = (p) => {
    if (p.id === provider) { setOpen(false); return }
    setPendingId(p.id)
    setApiKey('')
    if (p.id === 'ollama') {
      doSwitch(p.id, null)
    }
    // For cloud providers, show key input
  }

  const doSwitch = async (id, key) => {
    setSwitching(true)
    await switchProvider(id, key || undefined)
    setSwitching(false)
    setPendingId(null)
    setApiKey('')
    setOpen(false)
  }

  return (
    <div className="px-3 pb-2">
      {/* Current provider badge — click to open */}
      <button
        id="provider-selector-btn"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-xl glass-sm border border-white/8 hover:border-white/15 transition-all duration-200 group"
      >
        <span className="text-base">{current.icon}</span>
        <div className="flex-1 text-left">
          <div className="text-xs font-semibold text-slate-200">{current.label}</div>
          <div className="text-[10px] text-slate-500">
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

          {PROVIDERS.map(p => (
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
          {pendingId && pendingId !== 'ollama' && (
            <div className="border-t border-white/8 p-3 space-y-2">
              <p className="text-[10px] text-slate-400">
                Enter your {PROVIDERS.find(p => p.id === pendingId)?.label} API key:
              </p>
              <input
                id="provider-api-key-input"
                type="password"
                placeholder="Paste API key here..."
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && apiKey && doSwitch(pendingId, apiKey)}
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50 focus:ring-1 focus:ring-brand-500/20"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  id="provider-connect-btn"
                  onClick={() => doSwitch(pendingId, apiKey)}
                  disabled={!apiKey || switching}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #4f46e5)', color: 'white' }}
                >
                  {switching ? 'Connecting...' : 'Connect'}
                </button>
                <button
                  onClick={() => { setPendingId(null); setApiKey('') }}
                  className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-all"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
