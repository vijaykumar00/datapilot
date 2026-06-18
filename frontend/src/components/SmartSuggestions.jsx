import { useState, useEffect } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

// ── Type config ───────────────────────────────────────────────────────────────
const TYPE_CONFIG = {
  forecast: {
    border: 'border-l-violet-500',
    badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    glow: 'hover:shadow-[0_0_20px_-5px_rgba(139,92,246,0.25)]',
    dot: 'bg-violet-500',
  },
  insight: {
    border: 'border-l-brand-500',
    badge: 'bg-brand-500/15 text-brand-300 border-brand-500/30',
    glow: 'hover:shadow-[0_0_20px_-5px_rgba(99,102,241,0.25)]',
    dot: 'bg-brand-500',
  },
  clean: {
    border: 'border-l-amber-500',
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    glow: 'hover:shadow-[0_0_20px_-5px_rgba(245,158,11,0.25)]',
    dot: 'bg-amber-500',
  },
  visualize: {
    border: 'border-l-sky-500',
    badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    glow: 'hover:shadow-[0_0_20px_-5px_rgba(14,165,233,0.25)]',
    dot: 'bg-sky-500',
  },
  summary: {
    border: 'border-l-emerald-500',
    badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    glow: 'hover:shadow-[0_0_20px_-5px_rgba(16,185,129,0.25)]',
    dot: 'bg-emerald-500',
  },
}

const DEFAULT_CONFIG = {
  border: 'border-l-slate-500',
  badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  glow: 'hover:shadow-[0_0_20px_-5px_rgba(100,116,139,0.25)]',
  dot: 'bg-slate-500',
}

const PRIORITY_LABELS = {
  1: { label: 'Action Required', color: 'text-rose-400' },
  2: { label: 'Recommended', color: 'text-amber-400' },
  3: { label: 'Available', color: 'text-slate-500' },
}

// ── Persistence helpers ───────────────────────────────────────────────────────
function getDismissedKey(fileId) {
  return `datapilot_dismissed_${fileId}`
}

function getDismissed(fileId) {
  try {
    const raw = sessionStorage.getItem(getDismissedKey(fileId))
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function saveDismissed(fileId, dismissedSet) {
  try {
    sessionStorage.setItem(getDismissedKey(fileId), JSON.stringify([...dismissedSet]))
  } catch { /* quota */ }
}

// ── Individual suggestion card ────────────────────────────────────────────────
function SuggestionCard({ suggestion, index, onAction, onDismiss }) {
  const [isActing, setIsActing] = useState(false)
  const cfg = TYPE_CONFIG[suggestion.type] || DEFAULT_CONFIG
  const priorityInfo = PRIORITY_LABELS[suggestion.priority] || PRIORITY_LABELS[3]

  const handleAction = async () => {
    setIsActing(true)
    await onAction(suggestion.prompt)
    // Don't reset — card will be dismissed naturally after the query fires
  }

  return (
    <div
      className={`
        relative group rounded-xl border border-white/5 border-l-2 ${cfg.border}
        bg-[#080d18]/80 backdrop-blur
        px-4 py-3
        transition-all duration-300 ease-out
        ${cfg.glow}
        hover:bg-[#0c1220]/90 hover:border-white/10
        animate-slide-up
      `}
      style={{ animationDelay: `${index * 60}ms`, animationFillMode: 'both' }}
    >
      {/* Dismiss button */}
      <button
        onClick={() => onDismiss(suggestion.id)}
        className="absolute top-2 right-2.5 opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-slate-300 text-[10px] leading-none p-0.5 rounded"
        title="Dismiss suggestion"
        aria-label="Dismiss"
      >
        ✕
      </button>

      {/* Header row */}
      <div className="flex items-start gap-2.5 pr-5">
        <span className="text-xl leading-none mt-0.5 flex-shrink-0">{suggestion.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-[12px] font-semibold text-slate-100 leading-tight">
              {suggestion.title}
            </span>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${cfg.badge}`}>
              {suggestion.badge}
            </span>
            {suggestion.priority === 1 && (
              <span className="text-[9px] font-bold text-rose-400 flex items-center gap-0.5">
                <span className="w-1 h-1 rounded-full bg-rose-400 animate-pulse" />
                Action Required
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            {suggestion.description}
          </p>
        </div>
      </div>

      {/* Action button */}
      <button
        id={`suggestion-action-${suggestion.id}`}
        onClick={handleAction}
        disabled={isActing}
        className={`
          mt-2.5 ml-8 flex items-center gap-1.5 text-[10px] font-semibold
          px-2.5 py-1.5 rounded-lg border transition-all duration-200
          ${isActing
            ? 'border-brand-500/30 bg-brand-500/10 text-brand-300 cursor-not-allowed'
            : 'border-white/10 bg-white/5 text-slate-300 hover:bg-brand-500/20 hover:border-brand-500/40 hover:text-brand-200'
          }
        `}
      >
        {isActing ? (
          <>
            <div className="w-2.5 h-2.5 border border-brand-300 border-t-transparent rounded-full animate-spin" />
            Analyzing...
          </>
        ) : (
          <>
            <span>▶</span>
            Run Analysis
          </>
        )}
      </button>
    </div>
  )
}

// ── Main SmartSuggestions panel ───────────────────────────────────────────────
export default function SmartSuggestions() {
  const { suggestions, files, sendMessage, dismissSuggestion, clearSuggestions } = useDataPilot()
  const [collapsed, setCollapsed] = useState(false)
  const [dismissed, setDismissed] = useState(new Set())
  const [allDismissed, setAllDismissed] = useState(false)

  const activeFile = files[0]
  const fileId = activeFile?.file_id

  // Load persisted dismissed state when file changes
  useEffect(() => {
    if (fileId) {
      const saved = getDismissed(fileId)
      setDismissed(saved)
      setAllDismissed(false)
    }
  }, [fileId])

  if (!suggestions?.length || allDismissed) return null

  // Filter out dismissed suggestions
  const visibleSuggestions = suggestions.filter(s => !dismissed.has(s.id))
  if (!visibleSuggestions.length) return null

  const handleAction = async (prompt) => {
    await sendMessage(prompt)
  }

  const handleDismiss = (id) => {
    const next = new Set(dismissed)
    next.add(id)
    setDismissed(next)
    if (fileId) saveDismissed(fileId, next)
    dismissSuggestion(id)
  }

  const handleDismissAll = () => {
    const next = new Set(suggestions.map(s => s.id))
    setDismissed(next)
    if (fileId) saveDismissed(fileId, next)
    clearSuggestions()
    setAllDismissed(true)
  }

  // Count by priority for header badge
  const criticalCount = visibleSuggestions.filter(s => s.priority === 1).length

  return (
    <div className="mx-2 mb-3">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-2 px-1">
        <button
          id="smart-suggestions-toggle"
          onClick={() => setCollapsed(prev => !prev)}
          className="flex items-center gap-2 text-[11px] font-semibold text-slate-400 hover:text-slate-200 transition-colors group"
        >
          <div className="relative">
            <span className="text-brand-400 text-sm">✦</span>
            {criticalCount > 0 && (
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
            )}
          </div>
          <span>Smart Suggestions</span>
          <span className="text-[9px] bg-brand-500/15 text-brand-300 border border-brand-500/25 px-1.5 py-0.5 rounded-full font-bold">
            {visibleSuggestions.length}
          </span>
          {criticalCount > 0 && (
            <span className="text-[9px] bg-rose-500/15 text-rose-300 border border-rose-500/25 px-1.5 py-0.5 rounded-full font-bold flex items-center gap-1">
              <span className="w-1 h-1 rounded-full bg-rose-400 animate-pulse" />
              {criticalCount} action{criticalCount > 1 ? 's' : ''} required
            </span>
          )}
          <span className="text-slate-700 group-hover:text-slate-500 transition-colors ml-0.5">
            {collapsed ? '▸' : '▾'}
          </span>
        </button>

        {!collapsed && (
          <button
            onClick={handleDismissAll}
            className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors px-1.5 py-0.5 rounded border border-transparent hover:border-white/5"
          >
            Dismiss all
          </button>
        )}
      </div>

      {/* Cards grid */}
      {!collapsed && (
        <div className="space-y-2">
          {visibleSuggestions.map((s, i) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              index={i}
              onAction={handleAction}
              onDismiss={handleDismiss}
            />
          ))}

          {/* Footer hint */}
          <p className="text-[9px] text-slate-700 px-1 pt-0.5 flex items-center gap-1.5">
            <span>🔒</span>
            Suggestions generated from your data profile — no additional AI calls
          </p>
        </div>
      )}
    </div>
  )
}
