/**
 * Workspace home.  Answers, in order: what can I do now (ask / upload), what
 * data do I have, what did I work on recently, how much of my plan is left,
 * and what to do next (getting started).
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUp, Database, FileSpreadsheet, FileText, MessageSquare, Upload } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { useAuth } from '../contexts/AuthContext'
import { createBillingClient } from '../lib/billingClient'
import { GettingStarted } from './OnboardingAssistant'
import FileUploader from './FileUploader'
import { EmptyState, Skeleton } from './ui'

const QUESTIONS = [
  'Show monthly sales trends',
  'Find missing values',
  'Top products by profit',
  'Create an executive summary',
]

const openUpload = () => window.dispatchEvent(new Event('dp:open-upload'))

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return '—'
  }
}

function formatBytes(bytes) {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function SectionCard({ title, action, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <h2 className="text-md font-semibold text-fg">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function Meter({ label, current, limit }) {
  const unlimited = limit === null || limit === undefined || limit < 0
  const pct = unlimited ? 0 : Math.min(100, Math.round(((current || 0) / Math.max(limit, 1)) * 100))
  const tone = pct >= 90 ? 'bg-danger' : pct >= 70 ? 'bg-warning' : 'bg-primary'
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted">{label}</span>
        <span className="tabular font-medium text-fg">{(current || 0).toLocaleString()}{unlimited ? '' : ` of ${limit.toLocaleString()}`}</span>
      </div>
      {!unlimited && (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink/[0.08]" role="progressbar" aria-label={`${label} used`} aria-valuenow={current || 0} aria-valuemin={0} aria-valuemax={limit}>
          <div className={`h-full rounded-full ${tone}`} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

function UsageCard() {
  const { isGuest, isAuthenticated, guestUsage, guestLimits, apiHeaders } = useAuth()
  const [quota, setQuota] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!isAuthenticated) return undefined
    let cancelled = false
    createBillingClient(apiHeaders).getQuota()
      .then((data) => { if (!cancelled) setQuota(data.quota || {}) })
      .catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true }
  }, [isAuthenticated, apiHeaders])

  const rows = isGuest && !isAuthenticated
    ? [
      ['Uploads', guestUsage?.upload_count, guestLimits?.upload_count],
      ['Questions', guestUsage?.query_count, guestLimits?.query_count],
      ['Reports', guestUsage?.report_count, guestLimits?.report_count],
    ]
    : quota
      ? [
        ['Questions this month', quota.query_count?.current, quota.query_count?.limit],
        ['Uploads this month', quota.upload_count?.current, quota.upload_count?.limit],
        ['Reports this month', quota.report_count?.current, quota.report_count?.limit],
      ].filter((r) => r[1] !== undefined)
      : null

  return (
    <SectionCard title="Usage" action={<Link to="/app/billing" className="text-sm font-medium text-primary-text hover:underline">{isGuest && !isAuthenticated ? 'Plans' : 'Manage plan'}</Link>}>
      <div className="space-y-4 p-4 sm:p-5">
        {failed && <p className="text-sm text-muted">Usage isn't available right now.</p>}
        {!failed && !rows && (
          <>
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </>
        )}
        {rows?.map(([label, current, limit]) => <Meter key={label} label={label} current={current} limit={limit} />)}
      </div>
    </SectionCard>
  )
}

export default function DashboardHome() {
  const { files, datasetsList, datasetsLoading, reports, sessions, loadReports, loadDatasets, loadSessions, trackEvent, setChatPromptInput } = useDataPilot()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')

  useEffect(() => {
    loadReports?.()
    loadDatasets?.({ archived: 'all' })
    loadSessions?.(true)
  }, [])

  const datasets = useMemo(() => {
    const source = datasetsList?.length ? datasetsList : files
    return (source || []).filter((d) => !d.archived)
  }, [datasetsList, files])

  const firstName = (user?.full_name || '').split(' ')[0] || (user?.email ? user.email.split('@')[0] : '')
  const hasData = datasets.length > 0
  const recentReports = (reports || []).slice(0, 4)
  const recentChats = (sessions || []).slice(0, 5)

  const ask = (text) => {
    const prompt = (text ?? question).trim()
    if (!prompt) return
    trackEvent?.('DASHBOARD_PROMPT_CLICK', prompt)
    setChatPromptInput?.(prompt)
    navigate('/app/analyze', { state: { suggestedPrompt: prompt } })
  }

  return (
    <div className="h-full overflow-y-auto" data-testid="premium-dashboard">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold text-fg">
              {greeting()}{firstName ? `, ${firstName}` : ''}
            </h1>
            <p className="mt-1 text-base text-muted">
              {hasData ? 'Ask a question about your data, or pick up where you left off.' : 'Upload a spreadsheet to get your first answer in under a minute.'}
            </p>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={openUpload}><Upload className="h-4 w-4" aria-hidden="true" />Upload data</button>
            <Link to="/app/analyze" className="btn-primary"><MessageSquare className="h-4 w-4" aria-hidden="true" />Ask AI</Link>
          </div>
        </header>

        {/* Ask box: the fastest path to value */}
        <section className="mt-6 card p-4 sm:p-5" aria-labelledby="ask-title">
          <h2 id="ask-title" className="text-md font-semibold text-fg">Ask about your data</h2>
          <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask() }}>
            <label htmlFor="home-ask" className="sr-only">Your question</label>
            <input
              id="home-ask"
              className="input text-lg sm:text-base"
              placeholder={hasData ? 'e.g. Which region had the highest revenue last quarter?' : 'Upload a file first, then ask anything about it'}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={!hasData}
            />
            <button type="submit" className="btn-primary btn-icon h-[38px] w-[38px] flex-shrink-0" disabled={!hasData || !question.trim()} aria-label="Ask">
              <ArrowUp className="h-4 w-4" aria-hidden="true" />
            </button>
          </form>
          {hasData && (
            <div className="mt-3 flex flex-wrap gap-2">
              {QUESTIONS.map((q) => (
                <button key={q} type="button" className="chip hover:border-line-strong hover:bg-surface-muted" onClick={() => ask(q)}>{q}</button>
              ))}
            </div>
          )}
        </section>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="min-w-0 space-y-6 lg:col-span-2">
            <SectionCard
              title="Your data"
              action={hasData && <Link to="/app/datasets" className="text-sm font-medium text-primary-text hover:underline">All datasets</Link>}
            >
              {datasetsLoading && !hasData ? (
                <div className="space-y-2 p-4 sm:p-5"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
              ) : hasData ? (
                <ul className="divide-y divide-line">
                  {datasets.slice(0, 5).map((d) => {
                    const name = d.display_name || d.filename || 'Untitled dataset'
                    return (
                      <li key={d.dataset_id || d.file_id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                        <FileSpreadsheet className="h-5 w-5 flex-shrink-0 text-subtle" aria-hidden="true" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-base font-medium text-fg" title={name}>{name}</p>
                          <p className="truncate text-sm text-muted">
                            {(d.row_count || 0).toLocaleString()} rows · {d.column_count || 0} columns · {formatBytes(d.file_size_bytes)} · {formatDate(d.upload_date || d.created_at)}
                          </p>
                        </div>
                        <Link to="/app/analyze" className="btn-ghost btn-sm flex-shrink-0">Ask <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <div className="p-4 sm:p-5"><FileUploader showFiles={false} /></div>
              )}
            </SectionCard>

            <SectionCard title="Recent reports" action={<Link to="/app/saved?view=reports" className="text-sm font-medium text-primary-text hover:underline">All reports</Link>}>
              {recentReports.length ? (
                <ul className="divide-y divide-line">
                  {recentReports.map((r) => (
                    <li key={r.report_id}>
                      <Link to="/app/saved?view=reports" className="flex items-center gap-3 px-4 py-3 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus sm:px-5">
                        <FileText className="h-5 w-5 flex-shrink-0 text-subtle" aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-base font-medium text-fg">{r.title}</span>
                          <span className="block truncate text-sm text-muted">{r.description || 'Saved report'} · {formatDate(r.created_at)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  compact
                  icon={FileText}
                  title="No reports yet"
                  description="Turn an answer into a shareable brief with charts and key numbers."
                  action={<Link to="/app/reports?view=builder" className="btn-secondary btn-sm">Build a report</Link>}
                />
              )}
            </SectionCard>
          </div>

          <aside className="min-w-0 space-y-6">
            <GettingStarted />
            <UsageCard />
            <SectionCard title="Recent conversations" action={recentChats.length > 0 && <Link to="/app/analyze" className="text-sm font-medium text-primary-text hover:underline">Open chat</Link>}>
              {recentChats.length ? (
                <ul className="divide-y divide-line">
                  {recentChats.map((s) => (
                    <li key={s.session_id}>
                      <Link to="/app/analyze" className="block px-4 py-2.5 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus sm:px-5">
                        <span className="block truncate text-base text-fg">{s.name}</span>
                        <span className="block text-xs text-subtle">{formatDate(s.updated_at || s.created_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact icon={Database} title="No conversations yet" description="Your questions and answers are saved here." />
              )}
            </SectionCard>
          </aside>
        </div>
      </div>
    </div>
  )
}
