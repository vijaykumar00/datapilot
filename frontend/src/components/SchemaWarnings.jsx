import { useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

const SEVERITY_CONFIG = {
  critical: { icon: '🔴', dot: 'bg-rose-500',   bar: 'border-l-rose-500',   badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30',   label: 'Critical' },
  warning:  { icon: '🟡', dot: 'bg-amber-400',  bar: 'border-l-amber-500',  badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',  label: 'Warning'  },
  info:     { icon: '🔵', dot: 'bg-sky-400',     bar: 'border-l-sky-500',    badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30',        label: 'Info'     },
}

function WarningCard({ warning, onDismiss }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = SEVERITY_CONFIG[warning.severity] || SEVERITY_CONFIG.warning
  const suggestions = warning.suggestions || []

  return (
    <div className={`rounded-xl border border-white/5 border-l-2 ${cfg.bar} bg-[#080d18]/70 overflow-hidden animate-slide-up`}>
      {/* Header */}
      <div className="flex items-start gap-2.5 px-3.5 py-2.5">
        <span className="text-sm leading-none mt-0.5 flex-shrink-0">{cfg.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
            <h4 className="text-[11px] font-bold text-slate-200 leading-tight">
              {warning.title}
            </h4>
            <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded-full border ${cfg.badge}`}>
              {cfg.label}
            </span>
          </div>
          <p className="text-[10px] text-slate-400 leading-snug">
            {warning.message}
          </p>
          {warning.affected_column && (
            <span className="inline-block mt-1 text-[8px] font-mono text-brand-300 bg-brand-500/10 border border-brand-500/20 px-1.5 py-0.5 rounded-md">
              📋 {warning.affected_column}
            </span>
          )}
        </div>
        <button
          onClick={() => onDismiss(warning.code + (warning.affected_column || ''))}
          className="flex-shrink-0 text-[10px] text-slate-600 hover:text-slate-400 transition-colors px-1"
          title="Dismiss"
        >
          ✕
        </button>
      </div>

      {/* Suggestions toggle */}
      {suggestions.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(v => !v)}
            className="w-full flex items-center justify-between px-3.5 py-1.5 border-t border-white/5 text-[9px] text-slate-600 hover:text-slate-400 transition-colors"
          >
            <span>🔧 {suggestions.length} fix{suggestions.length > 1 ? 'es' : ''} available</span>
            <span>{expanded ? '▲' : '▼'}</span>
          </button>
          {expanded && (
            <div className="px-3.5 pb-2.5 pt-1 space-y-1 animate-fade-in border-t border-white/5 bg-black/10">
              {suggestions.map((s, i) => (
                <p key={i} className="text-[10px] text-slate-400 flex items-start gap-1.5">
                  <span className="text-brand-400 font-bold flex-shrink-0">{i + 1}.</span>
                  {s}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/**
 * SchemaWarnings
 * Dismissible banner shown after file upload when schema_warnings are present.
 * Sits above SmartSuggestions in the chat area.
 */
export default function SchemaWarnings() {
  const { schemaWarnings, dismissSchemaWarning } = useDataPilot()

  const [allDismissed, setAllDismissed] = useState(false)
  const [bannerOpen, setBannerOpen] = useState(true)

  if (!schemaWarnings?.length || allDismissed || !bannerOpen) return null

  const criticalCount = schemaWarnings.filter(w => w.severity === 'critical').length
  const warningCount = schemaWarnings.filter(w => w.severity === 'warning').length
  const infoCount = schemaWarnings.filter(w => w.severity === 'info').length

  const headerColor = criticalCount > 0
    ? 'border-rose-500/30 bg-rose-500/5'
    : warningCount > 0
    ? 'border-amber-500/30 bg-amber-500/5'
    : 'border-sky-500/30 bg-sky-500/5'

  const [listOpen, setListOpen] = useState(false)

  const handleDismissOne = (key) => {
    dismissSchemaWarning(key)
  }

  const handleDismissAll = () => {
    setAllDismissed(true)
  }

  return (
    <div
      id="schema-warnings-panel"
      className={`mx-4 mt-3 rounded-xl border ${headerColor} overflow-hidden`}
    >
      {/* Summary bar */}
      <div className="flex items-center gap-2 px-3.5 py-2.5">
        <span className="text-base flex-shrink-0">🔬</span>
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-bold text-slate-200">
            Schema Diagnostics — {schemaWarnings.length} issue{schemaWarnings.length > 1 ? 's' : ''} detected
          </p>
          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
            {criticalCount > 0 && (
              <span className="text-[8px] bg-rose-500/15 text-rose-300 border border-rose-500/30 px-1.5 py-0.5 rounded-full font-bold">
                🔴 {criticalCount} critical
              </span>
            )}
            {warningCount > 0 && (
              <span className="text-[8px] bg-amber-500/15 text-amber-300 border border-amber-500/30 px-1.5 py-0.5 rounded-full font-bold">
                🟡 {warningCount} warning{warningCount > 1 ? 's' : ''}
              </span>
            )}
            {infoCount > 0 && (
              <span className="text-[8px] bg-sky-500/15 text-sky-300 border border-sky-500/30 px-1.5 py-0.5 rounded-full font-bold">
                🔵 {infoCount} info
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <button
            onClick={() => setListOpen(v => !v)}
            className="text-[9px] font-semibold text-slate-400 hover:text-slate-200 px-2 py-1 rounded-lg border border-white/8 hover:border-white/15 transition-all"
          >
            {listOpen ? 'Hide' : 'View all'}
          </button>
          <button
            onClick={handleDismissAll}
            className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
            title="Dismiss all warnings"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Warning cards list */}
      {listOpen && (
        <div className="px-3.5 pb-3 space-y-2 border-t border-white/5 pt-2.5 animate-fade-in">
          {schemaWarnings.map((w, i) => (
            <WarningCard
              key={`${w.code}-${w.affected_column || i}`}
              warning={w}
              onDismiss={handleDismissOne}
            />
          ))}
        </div>
      )}
    </div>
  )
}
