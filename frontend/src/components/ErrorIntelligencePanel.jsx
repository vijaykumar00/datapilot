import { useState } from 'react'

const SEVERITY_CONFIG = {
  critical: { icon: '🔴', label: 'Critical',  bg: 'bg-rose-500/10',    border: 'border-rose-500/25',    text: 'text-rose-300',    badge: 'bg-rose-500/20 text-rose-300 border-rose-500/35' },
  error:    { icon: '🔴', label: 'Error',     bg: 'bg-rose-500/8',     border: 'border-rose-500/20',    text: 'text-rose-300',    badge: 'bg-rose-500/15 text-rose-300 border-rose-500/25' },
  warning:  { icon: '🟡', label: 'Warning',   bg: 'bg-amber-500/8',    border: 'border-amber-500/20',   text: 'text-amber-300',   badge: 'bg-amber-500/15 text-amber-300 border-amber-500/25' },
  info:     { icon: '🔵', label: 'Info',      bg: 'bg-sky-500/8',      border: 'border-sky-500/20',     text: 'text-sky-300',     badge: 'bg-sky-500/15 text-sky-300 border-sky-500/25' },
}
const DEFAULT_SEV = SEVERITY_CONFIG.error

/**
 * ErrorIntelligencePanel
 * Renders a structured IntelligentError dict from metadata.intelligent_error.
 * Replaces raw red error text with a professional diagnostic card.
 */
export default function ErrorIntelligencePanel({ intelligentError, fallbackMessage }) {
  const [suggestionsOpen, setSuggestionsOpen] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(false)

  // If no intelligent error dict, fall back to plain text rendering
  if (!intelligentError) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3.5 text-[12px] text-rose-300">
        <span className="mr-2">🔴</span>
        {fallbackMessage || 'An error occurred. Please try again.'}
      </div>
    )
  }

  const sev = SEVERITY_CONFIG[intelligentError.severity] || DEFAULT_SEV
  const suggestions = intelligentError.suggestions || []
  const details = intelligentError.details || []
  const hasAffectedRows = intelligentError.affected_rows?.[0] != null

  return (
    <div className={`rounded-xl border ${sev.border} ${sev.bg} overflow-hidden animate-slide-up`}>
      {/* Header row */}
      <div className="flex items-start gap-2.5 px-4 py-3">
        <span className="text-base leading-none mt-0.5 flex-shrink-0">{sev.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className={`text-[12px] font-bold leading-tight ${sev.text}`}>
              {intelligentError.title}
            </h3>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${sev.badge}`}>
              {sev.label}
            </span>
            {intelligentError.code && (
              <span className="text-[8px] font-mono text-slate-600 bg-white/5 px-1.5 py-0.5 rounded-md border border-white/5">
                {intelligentError.code}
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-300 leading-relaxed">
            {intelligentError.message}
          </p>
          {/* Affected column / rows pills */}
          {(intelligentError.affected_column || hasAffectedRows) && (
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              {intelligentError.affected_column && (
                <span className="text-[9px] font-mono text-brand-300 bg-brand-500/10 border border-brand-500/20 px-1.5 py-0.5 rounded-md">
                  📋 {intelligentError.affected_column}
                </span>
              )}
              {hasAffectedRows && (
                <span className="text-[9px] font-mono text-slate-400 bg-white/5 border border-white/8 px-1.5 py-0.5 rounded-md">
                  📍 rows {intelligentError.affected_rows[0]}–{intelligentError.affected_rows[1]}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <div className="border-t border-white/5">
          <button
            onClick={() => setSuggestionsOpen(v => !v)}
            className="w-full flex items-center justify-between px-4 py-2 text-[10px] font-semibold text-slate-500 hover:text-slate-300 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              🔧 Suggested fixes ({suggestions.length})
            </span>
            <span className="text-slate-600">{suggestionsOpen ? '▲' : '▼'}</span>
          </button>
          {suggestionsOpen && (
            <div className="px-4 pb-3 space-y-1.5 animate-fade-in">
              {suggestions.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] text-slate-300">
                  <span className="text-brand-400 mt-0.5 flex-shrink-0 font-bold">{i + 1}.</span>
                  <span className="leading-snug">{s}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Extra details (collapsed by default) */}
      {details.length > 0 && (
        <div className="border-t border-white/5">
          <button
            onClick={() => setDetailsOpen(v => !v)}
            className="w-full flex items-center justify-between px-4 py-2 text-[10px] font-semibold text-slate-600 hover:text-slate-400 transition-colors"
          >
            <span>Technical details</span>
            <span>{detailsOpen ? '▲' : '▼'}</span>
          </button>
          {detailsOpen && (
            <div className="px-4 pb-3 space-y-1 animate-fade-in">
              {details.map((d, i) => (
                <p key={i} className="text-[10px] text-slate-500 font-mono leading-snug">{d}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
