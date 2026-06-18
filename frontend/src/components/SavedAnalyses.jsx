import { useState, useMemo } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

// ── Type config (mirrors SmartSuggestions palette) ─────────────────────────────
const TYPE_CONFIG = {
  insight:  { border: 'border-l-brand-500',   badge: 'bg-brand-500/15 text-brand-300 border-brand-500/30',   icon: '💡', label: 'Insight'  },
  forecast: { border: 'border-l-violet-500',  badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30', icon: '🔮', label: 'Forecast' },
  chart:    { border: 'border-l-sky-500',     badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30',         icon: '📊', label: 'Chart'    },
  summary:  { border: 'border-l-emerald-500', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', icon: '📋', label: 'Summary'  },
  clean:    { border: 'border-l-amber-500',   badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',   icon: '🧹', label: 'Clean'    },
}
const DEFAULT_CFG = { border: 'border-l-slate-500', badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30', icon: '✦', label: 'Analysis' }

const ALL_TYPES = ['all', 'insight', 'forecast', 'chart', 'summary', 'clean']

function formatRelativeTime(iso) {
  if (!iso) return ''
  try {
    const diff = Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}d ago`
    return new Date(iso).toLocaleDateString()
  } catch {
    return ''
  }
}

// ── Individual analysis card ───────────────────────────────────────────────────
function AnalysisCard({ analysis, onReplay, onRestore, onStar, onDelete }) {
  const cfg = TYPE_CONFIG[analysis.type] || DEFAULT_CFG
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [starring, setStarring] = useState(false)

  const handleStar = async () => {
    setStarring(true)
    await onStar(analysis.analysis_id, !analysis.starred)
    setStarring(false)
  }

  return (
    <div
      className={`
        relative group rounded-xl border border-white/5 border-l-2 ${cfg.border}
        bg-[#080d18]/80 backdrop-blur px-4 py-3.5
        transition-all duration-300 hover:bg-[#0c1220]/90 hover:border-white/10
        animate-slide-up
      `}
    >
      {/* Top row */}
      <div className="flex items-start gap-2.5 pr-2">
        <span className="text-lg leading-none mt-0.5 flex-shrink-0">{cfg.icon}</span>
        <div className="flex-1 min-w-0">
          {/* Title + badges */}
          <div className="flex items-center flex-wrap gap-1.5 mb-1">
            <h3 className="text-[12px] font-semibold text-slate-100 leading-tight truncate max-w-[220px]">
              {analysis.title}
            </h3>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${cfg.badge} flex-shrink-0`}>
              {cfg.label}
            </span>
            {analysis.starred && (
              <span className="text-[9px] text-amber-400">⭐</span>
            )}
          </div>

          {/* Query preview */}
          <p className="text-[10px] text-slate-500 italic leading-snug truncate mb-1.5">
            "{analysis.query}"
          </p>

          {/* Meta row */}
          <div className="flex items-center gap-3 flex-wrap">
            {analysis.filename && (
              <span className="text-[9px] text-brand-400/80 bg-brand-500/8 border border-brand-500/20 px-1.5 py-0.5 rounded-md font-mono">
                📄 {analysis.filename}
              </span>
            )}
            {analysis.tags?.length > 0 && analysis.tags.map(tag => (
              <span key={tag} className="text-[9px] text-slate-500 bg-white/5 border border-white/8 px-1.5 py-0.5 rounded-md">
                #{tag}
              </span>
            ))}
            <span className="text-[9px] text-slate-600 ml-auto">
              {formatRelativeTime(analysis.created_at)}
            </span>
          </div>
        </div>

        {/* Actions column */}
        <div className="flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            onClick={handleStar}
            disabled={starring}
            title={analysis.starred ? 'Unstar' : 'Star'}
            className="w-6 h-6 flex items-center justify-center text-[11px] rounded-md border border-white/8 hover:border-amber-500/30 hover:bg-amber-500/10 text-slate-500 hover:text-amber-400 transition-all"
          >
            {starring ? '…' : analysis.starred ? '★' : '☆'}
          </button>
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              title="Delete"
              className="w-6 h-6 flex items-center justify-center text-[11px] rounded-md border border-white/8 hover:border-rose-500/30 hover:bg-rose-500/10 text-slate-500 hover:text-rose-400 transition-all"
            >
              ✕
            </button>
          ) : (
            <button
              onClick={() => onDelete(analysis.analysis_id)}
              title="Confirm delete"
              className="w-6 h-6 flex items-center justify-center text-[9px] rounded-md border border-rose-500/40 bg-rose-500/15 text-rose-400 transition-all font-bold"
            >
              ✓
            </button>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 mt-3 ml-8">
        <button
          id={`replay-${analysis.analysis_id}`}
          onClick={() => onReplay(analysis)}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold border border-white/10 bg-white/5 text-slate-300 hover:bg-brand-500/20 hover:border-brand-500/40 hover:text-brand-200 transition-all"
        >
          <span>▶</span> Replay
        </button>
        <button
          id={`restore-${analysis.analysis_id}`}
          onClick={() => onRestore(analysis)}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold border border-white/10 bg-white/5 text-slate-300 hover:bg-violet-500/20 hover:border-violet-500/40 hover:text-violet-200 transition-all"
        >
          <span>↩</span> Restore
        </button>
      </div>
    </div>
  )
}

// ── Empty state ────────────────────────────────────────────────────────────────
function EmptyState({ filterActive }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center select-none">
      <div className="text-5xl mb-4 opacity-30">💾</div>
      <h3 className="text-[13px] font-semibold text-slate-500 mb-1">
        {filterActive ? 'No matching analyses' : 'No saved analyses yet'}
      </h3>
      <p className="text-[11px] text-slate-600 max-w-[240px] leading-relaxed">
        {filterActive
          ? 'Try clearing the filters to see all saved analyses.'
          : 'Hover over any AI response in chat and click 💾 Save to bookmark it here.'}
      </p>
    </div>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────────
export default function SavedAnalyses() {
  const {
    savedAnalyses,
    savedAnalysesLoading,
    loadSavedAnalyses,
    replayAnalysis,
    restoreAnalysis,
    starAnalysis,
    deleteSavedAnalysis,
  } = useDataPilot()

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [starredOnly, setStarredOnly] = useState(false)

  // Initial load
  const [loaded, setLoaded] = useState(false)
  if (!loaded) {
    setLoaded(true)
    loadSavedAnalyses()
  }

  const filtered = useMemo(() => {
    return (savedAnalyses || []).filter(a => {
      if (starredOnly && !a.starred) return false
      if (typeFilter !== 'all' && a.type !== typeFilter) return false
      if (search) {
        const q = search.toLowerCase()
        if (
          !a.title.toLowerCase().includes(q) &&
          !a.query.toLowerCase().includes(q) &&
          !(a.filename || '').toLowerCase().includes(q) &&
          !(a.tags || []).some(t => t.toLowerCase().includes(q))
        ) return false
      }
      return true
    })
  }, [savedAnalyses, search, typeFilter, starredOnly])

  const filterActive = search || typeFilter !== 'all' || starredOnly

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-white/5 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-brand-400">💾</span>
            <h2 className="text-[13px] font-bold text-slate-200">Saved Analyses</h2>
            {savedAnalyses?.length > 0 && (
              <span className="text-[9px] bg-brand-500/15 text-brand-300 border border-brand-500/25 px-1.5 py-0.5 rounded-full font-bold">
                {savedAnalyses.length}
              </span>
            )}
          </div>
          <button
            onClick={() => loadSavedAnalyses()}
            title="Refresh"
            className="text-[10px] text-slate-600 hover:text-slate-300 transition-colors px-2 py-1 rounded-lg hover:bg-white/5"
          >
            ↻
          </button>
        </div>

        {/* Search */}
        <input
          id="saved-analyses-search"
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by title, query, tag…"
          className="w-full bg-white/5 border border-white/8 rounded-xl px-3 py-2 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-brand-500/40 transition-all mb-2.5"
        />

        {/* Type filter chips */}
        <div className="flex gap-1.5 flex-wrap">
          {ALL_TYPES.map(t => {
            const cfg = TYPE_CONFIG[t]
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`text-[9px] font-bold px-2 py-1 rounded-full border transition-all ${
                  typeFilter === t
                    ? 'bg-brand-500/20 border-brand-500/40 text-brand-300'
                    : 'bg-white/5 border-white/8 text-slate-500 hover:border-white/15 hover:text-slate-300'
                }`}
              >
                {cfg ? `${cfg.icon} ${cfg.label}` : 'All'}
              </button>
            )
          })}
          <button
            onClick={() => setStarredOnly(v => !v)}
            className={`text-[9px] font-bold px-2 py-1 rounded-full border transition-all ml-auto ${
              starredOnly
                ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                : 'bg-white/5 border-white/8 text-slate-500 hover:border-white/15 hover:text-slate-300'
            }`}
          >
            ⭐ Starred
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-3 space-y-2.5">
        {savedAnalysesLoading ? (
          <div className="flex items-center justify-center py-12 text-slate-600 text-[11px] gap-2">
            <span className="w-4 h-4 border-2 border-slate-600 border-t-brand-500 rounded-full animate-spin" />
            Loading…
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState filterActive={!!filterActive} />
        ) : (
          filtered.map((a, i) => (
            <AnalysisCard
              key={a.analysis_id}
              analysis={a}
              onReplay={replayAnalysis}
              onRestore={restoreAnalysis}
              onStar={starAnalysis}
              onDelete={deleteSavedAnalysis}
            />
          ))
        )}
      </div>

      {/* Footer hint */}
      {!savedAnalysesLoading && filtered.length > 0 && (
        <div className="px-5 py-2.5 border-t border-white/5 flex-shrink-0">
          <p className="text-[9px] text-slate-700 flex items-center gap-1.5">
            <span>🔒</span>
            Saved analyses are stored locally in your DataPilot database
          </p>
        </div>
      )}
    </div>
  )
}
