import { useState, useEffect, useRef } from 'react'

const TYPE_OPTIONS = [
  { value: 'insight',   label: 'Insight',   icon: '💡' },
  { value: 'forecast',  label: 'Forecast',  icon: '🔮' },
  { value: 'chart',     label: 'Chart',     icon: '📊' },
  { value: 'summary',   label: 'Summary',   icon: '📋' },
  { value: 'clean',     label: 'Clean',     icon: '🧹' },
]

function inferType(msg) {
  const meta = msg?.metadata?.type || msg?.type || ''
  if (meta === 'chart' || msg?.chart_data) return 'chart'
  if (meta === 'forecast') return 'forecast'
  if (meta === 'summary' || meta === 'greeting') return 'summary'
  if (meta === 'clean') return 'clean'
  return 'insight'
}

function autoTitle(query) {
  if (!query) return 'Saved Analysis'
  return query.length > 60 ? query.slice(0, 57) + '…' : query
}

// ── Modal ─────────────────────────────────────────────────────────────────────
export default function SaveAnalysisModal({ message, onSave, onClose }) {
  const [title, setTitle] = useState(() => autoTitle(message?.userQuery || message?.content || ''))
  const [tags, setTags] = useState('')
  const [type, setType] = useState(() => inferType(message))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const titleRef = useRef(null)

  useEffect(() => {
    titleRef.current?.focus()
    titleRef.current?.select()

    const modalEl = document.querySelector('.glass') // Targets modal container
    if (!modalEl) return

    const focusableSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    
    const handleKeyTab = (e) => {
      if (e.key === 'Tab') {
        const focusables = Array.from(modalEl.querySelectorAll(focusableSelector))
        if (focusables.length === 0) return
        
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        
        if (e.shiftKey) {
          if (document.activeElement === first) {
            last.focus()
            e.preventDefault()
          }
        } else {
          if (document.activeElement === last) {
            first.focus()
            e.preventDefault()
          }
        }
      }
    }

    window.addEventListener('keydown', handleKeyTab)
    return () => window.removeEventListener('keydown', handleKeyTab)
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    try {
      const tagList = tags
        .split(',')
        .map(t => t.trim())
        .filter(Boolean)
      await onSave({ title: title.trim(), type, tags: tagList })
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to save')
      setSaving(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') onClose()
  }


  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onKeyDown={handleKeyDown}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-md mx-4 glass rounded-2xl border border-white/10 shadow-2xl overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/8 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-lg">💾</span>
            <h2 className="text-[14px] font-bold text-slate-100">Save Analysis</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 text-lg leading-none transition-colors"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
              Title
            </label>
            <input
              ref={titleRef}
              id="save-analysis-title"
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              maxLength={200}
              required
              placeholder="Give this analysis a name…"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3.5 py-2.5 text-[12px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/10 transition-all"
            />
          </div>

          {/* Type */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
              Type
            </label>
            <div className="flex gap-2 flex-wrap">
              {TYPE_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setType(opt.value)}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold border transition-all duration-150 ${
                    type === opt.value
                      ? 'bg-brand-500/20 border-brand-500/50 text-brand-200'
                      : 'bg-white/5 border-white/10 text-slate-400 hover:border-white/20 hover:text-slate-200'
                  }`}
                >
                  <span>{opt.icon}</span>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
              Tags <span className="text-slate-600 font-normal normal-case">(comma-separated, optional)</span>
            </label>
            <input
              id="save-analysis-tags"
              type="text"
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="e.g. revenue, Q1, forecast"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3.5 py-2.5 text-[12px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50 focus:ring-2 focus:ring-brand-500/10 transition-all"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-[11px] text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2">
              ⚠ {error}
            </p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2.5 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-[11px] font-semibold text-slate-400 hover:text-slate-200 border border-white/8 hover:border-white/15 transition-all"
            >
              Cancel
            </button>
            <button
              type="submit"
              id="save-analysis-submit"
              disabled={!title.trim() || saving}
              className="btn-primary px-5 py-2 rounded-xl text-[11px] font-bold flex items-center gap-2 disabled:opacity-50"
            >
              {saving ? (
                <>
                  <span className="w-3 h-3 border border-white/30 border-t-white rounded-full animate-spin" />
                  Saving…
                </>
              ) : (
                <>💾 Save Analysis</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
