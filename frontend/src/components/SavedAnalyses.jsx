import { useEffect, useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart3, Bookmark, FileSpreadsheet, FileText, Lightbulb, MessageSquare, RefreshCw, RotateCcw,
  Search, Sparkles, Star, Trash2, TrendingUp,
} from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { Badge, Button, EmptyState, ErrorState, IconButton, PageHeader, Skeleton, cx } from './ui'

const TYPE_CONFIG = {
  insight: { icon: Lightbulb, label: 'Insight', tone: 'primary' },
  forecast: { icon: TrendingUp, label: 'Forecast', tone: 'info' },
  chart: { icon: BarChart3, label: 'Chart', tone: 'info' },
  summary: { icon: FileText, label: 'Summary', tone: 'success' },
  clean: { icon: Sparkles, label: 'Clean-up', tone: 'warning' },
}
const DEFAULT_CFG = { icon: Bookmark, label: 'Analysis', tone: 'neutral' }

const ALL_TYPES = ['all', 'insight', 'forecast', 'chart', 'summary', 'clean']

function formatRelativeTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? '' : 'Z'))
  if (Number.isNaN(d.getTime())) return '—'
  const mins = Math.floor((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days} d ago`
  return d.toLocaleDateString()
}

const GRID = 'lg:grid lg:grid-cols-[minmax(0,1fr)_110px_110px_260px] lg:items-center lg:gap-3'

function AnalysisRow({ analysis, onReplay, onRestore, onStar, onDelete }) {
  const cfg = TYPE_CONFIG[analysis.type] || DEFAULT_CFG
  const TypeIcon = cfg.icon
  const [starring, setStarring] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const title = analysis.title || 'Untitled analysis'

  const handleStar = async () => {
    setStarring(true)
    await onStar(analysis)
    setStarring(false)
  }

  const handleDelete = async () => {
    if (!window.confirm(`Delete "${title}"? This saved analysis will be removed. This cannot be undone.`)) return
    setDeleting(true)
    const ok = await onDelete(analysis)
    if (!ok) setDeleting(false)
  }

  return (
    <li className={cx('flex flex-col gap-3 px-4 py-3', GRID, deleting && 'opacity-60')} aria-busy={deleting || undefined}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-surface-muted text-muted">
          <TypeIcon className="h-[18px] w-[18px]" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="truncate text-md font-medium text-fg" title={title}>{title}</span>
            {analysis.starred && (
              <Badge tone="warning"><Star className="h-3 w-3 fill-current" aria-hidden="true" />Starred</Badge>
            )}
            <Badge tone={cfg.tone} className="lg:hidden">{cfg.label}</Badge>
          </p>
          {analysis.query && (
            <p className="mt-0.5 line-clamp-2 break-words text-sm text-muted">
              <span className="sr-only">Question: </span>{analysis.query}
            </p>
          )}
          {(analysis.filename || analysis.tags?.length > 0) && (
            <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="Details">
              {analysis.filename && (
                <li className="chip" title={analysis.filename}>
                  <FileSpreadsheet className="h-3.5 w-3.5 flex-shrink-0 text-subtle" aria-hidden="true" />
                  <span className="truncate">{analysis.filename}</span>
                </li>
              )}
              {(analysis.tags || []).map(tag => <li key={tag} className="chip">{tag}</li>)}
            </ul>
          )}
          <p className="mt-1 text-sm text-subtle lg:hidden">Saved {formatRelativeTime(analysis.created_at).toLowerCase()}</p>
        </div>
      </div>
      <span className="hidden lg:block"><Badge tone={cfg.tone}>{cfg.label}</Badge></span>
      <span className="hidden text-base text-muted lg:block">{formatRelativeTime(analysis.created_at)}</span>
      <div className="flex flex-wrap items-center gap-1 lg:justify-end">
        <Button
          id={`restore-${analysis.analysis_id}`}
          size="sm"
          variant="secondary"
          icon={MessageSquare}
          onClick={() => onRestore(analysis)}
          title="Show the saved answer in chat without asking again"
        >
          Open
        </Button>
        <Button
          id={`replay-${analysis.analysis_id}`}
          size="sm"
          variant="ghost"
          icon={RotateCcw}
          onClick={() => onReplay(analysis)}
          className="mr-auto lg:mr-0"
          title="Ask the same question again with the latest data"
        >
          Ask again
        </Button>
        <IconButton
          icon={Star}
          label={analysis.starred ? `Unstar ${title}` : `Star ${title}`}
          tooltipSide="top"
          aria-pressed={!!analysis.starred}
          className={analysis.starred ? 'text-warning [&>svg]:fill-current' : undefined}
          disabled={starring || deleting}
          onClick={handleStar}
        />
        <IconButton
          icon={Trash2}
          label={`Delete ${title}`}
          tooltipSide="top"
          className="hover:text-danger"
          disabled={deleting}
          onClick={handleDelete}
        />
      </div>
    </li>
  )
}

export default function SavedAnalyses() {
  const navigate = useNavigate()
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
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const searchId = useId()
  const typeId = useId()

  const reload = async () => {
    setLoadError('')
    const res = await loadSavedAnalyses()
    if (res && res.success === false) setLoadError(res.error || 'The server did not respond.')
  }

  useEffect(() => {
    reload()
  }, [])

  const filtered = useMemo(() => {
    return (savedAnalyses || []).filter(a => {
      if (starredOnly && !a.starred) return false
      if (typeFilter !== 'all' && a.type !== typeFilter) return false
      if (search) {
        const q = search.toLowerCase()
        if (
          !(a.title || '').toLowerCase().includes(q) &&
          !(a.query || '').toLowerCase().includes(q) &&
          !(a.filename || '').toLowerCase().includes(q) &&
          !(a.tags || []).some(t => t.toLowerCase().includes(q))
        ) return false
      }
      return true
    })
  }, [savedAnalyses, search, typeFilter, starredOnly])

  const filterActive = !!(search || typeFilter !== 'all' || starredOnly)
  const total = savedAnalyses?.length || 0

  const clearFilters = () => {
    setSearch('')
    setTypeFilter('all')
    setStarredOnly(false)
  }

  const handleReplay = (analysis) => {
    navigate('/app/analyze')
    replayAnalysis(analysis)
  }

  const handleRestore = (analysis) => {
    restoreAnalysis(analysis)
    navigate('/app/analyze')
  }

  const handleStar = async (analysis) => {
    setActionError('')
    const res = await starAnalysis(analysis.analysis_id, !analysis.starred)
    if (res && res.success === false) setActionError('Could not update the star. Check your connection and try again.')
  }

  const handleDelete = async (analysis) => {
    setActionError('')
    const res = await deleteSavedAnalysis(analysis.analysis_id)
    if (res && res.success === false) {
      setActionError(`Could not delete "${analysis.title || 'this analysis'}". Try again.`)
      return false
    }
    return true
  }

  const askAction = (
    <Button variant="primary" icon={MessageSquare} onClick={() => navigate('/app/analyze')}>Ask a question</Button>
  )

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6 lg:py-8">
      <PageHeader
        title="Saved answers"
        description="Answers you chose to keep. Open one to see it again, or ask the same question with the latest data."
        actions={(
          <Button icon={RefreshCw} loading={savedAnalysesLoading} onClick={reload}>Refresh</Button>
        )}
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_180px_auto] sm:items-end">
        <div className="min-w-0">
          <label htmlFor="saved-analyses-search" className="field-label">Search</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden="true" />
            <input
              id="saved-analyses-search"
              type="search"
              className="input pl-9"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Title, question, file or tag"
              aria-controls={searchId}
            />
          </div>
        </div>
        <div className="min-w-0">
          <label htmlFor={typeId} className="field-label">Type</label>
          <select id={typeId} className="input" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
            {ALL_TYPES.map(t => (
              <option key={t} value={t}>{TYPE_CONFIG[t]?.label || 'All types'}</option>
            ))}
          </select>
        </div>
        <Button
          variant="secondary"
          icon={Star}
          aria-pressed={starredOnly}
          onClick={() => setStarredOnly(v => !v)}
          className={cx(starredOnly && 'border-warning/40 bg-warning-soft text-warning')}
        >
          Starred only
        </Button>
      </div>

      {actionError && <p className="field-error" role="alert">{actionError}</p>}

      <section id={searchId} aria-label="Saved analyses" className="overflow-hidden rounded-lg border border-line bg-surface">
        {loadError && total === 0 ? (
          <div className="p-4">
            <ErrorState
              title="Could not load saved answers"
              description={`${loadError} Check your connection and try again.`}
              onRetry={reload}
            />
          </div>
        ) : savedAnalysesLoading && total === 0 ? (
          <ul className="divide-y divide-line" aria-busy="true" aria-label="Loading saved analyses">
            {[0, 1, 2, 3].map(i => (
              <li key={i} className="flex items-center gap-3 px-4 py-4">
                <Skeleton className="h-9 w-9 rounded-md" />
                <div className="flex-1 space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-3 w-1/2" /></div>
                <Skeleton className="hidden h-8 w-40 rounded-md sm:block" />
              </li>
            ))}
          </ul>
        ) : filtered.length === 0 ? (
          filterActive ? (
            <EmptyState
              icon={Search}
              title="No matching answers"
              description="Nothing matches these filters. Try a different search or show all types."
              action={<Button onClick={clearFilters}>Clear filters</Button>}
            />
          ) : (
            <EmptyState
              icon={Bookmark}
              title="No saved answers yet"
              description="Ask a question about your data, then select Save on any answer to keep it here."
              action={askAction}
            />
          )
        ) : (
          <>
            <div className={cx('hidden border-b border-line bg-surface-muted px-4 py-2 text-sm font-medium text-muted', GRID)} aria-hidden="true">
              <span>Analysis</span><span>Type</span><span>Saved</span><span className="text-right">Actions</span>
            </div>
            <ul className="divide-y divide-line">
              {filtered.map(a => (
                <AnalysisRow
                  key={a.analysis_id}
                  analysis={a}
                  onReplay={handleReplay}
                  onRestore={handleRestore}
                  onStar={handleStar}
                  onDelete={handleDelete}
                />
              ))}
            </ul>
          </>
        )}
      </section>

      {total > 0 && !loadError && (
        <p className="text-sm text-subtle" aria-live="polite">
          Showing {filtered.length.toLocaleString()} of {total.toLocaleString()} saved {total === 1 ? 'analysis' : 'analyses'}
        </p>
      )}
    </div>
  )
}
