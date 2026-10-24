/**
 * ChatWindow — the "Ask AI" workspace.
 *
 * Layout: conversation list (left, drawer on small screens) · conversation ·
 * composer pinned to the bottom.  Messages are visually distinct by role:
 *   user    — right-aligned bubble
 *   AI      — plain prose on the page, with a small "Tallis" label
 *   result  — bordered block with its own toolbar (tables, charts)
 *   system  — quiet one-line status rows
 * The view only auto-scrolls when the reader is already at the bottom, so
 * streaming never yanks the page while someone is reading earlier output.
 */
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useLocation } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, BarChart3, Bookmark, Check, Copy, Database, Download, FileSpreadsheet, LineChart, ListChecks,
  Loader2, MessagesSquare, PanelLeft, Paperclip, RotateCcw, Sigma, Sparkles, Square, Table2, Trash2, X, Zap,
} from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import ExplainPanel from './ExplainPanel'
import SaveAnalysisModal from './SaveAnalysisModal'
import ErrorIntelligencePanel from './ErrorIntelligencePanel'
import SchemaWarnings from './SchemaWarnings'
import SessionManager from './SessionManager'
import FileUploader from './FileUploader'
import SampleDataButton from './SampleDataButton'
import { IconButton, cx } from './ui'
import { LogoMark } from './ui/Logo'

const ChartRenderer = lazy(() => import('./ChartRenderer'))

const openUpload = () => window.dispatchEvent(new Event('dp:open-upload'))

// The raw SQL and row count are already shown in "How this was calculated" and
// the result table, so they are hidden from the prose (the saved text is unchanged).
function displayContent(msg) {
  const text = msg.content || ''
  if (!msg.metadata?.sql) return text
  return text
    .replace(/^\*\*Query:\*\* `[\s\S]*?`\s*$/m, '')
    .replace(/^\*\*\d[\d,]* row\(s\) returned\.\*\*\s*$/m, '')
    .trim()
}

function useCopy() {
  const [copied, setCopied] = useState(false)
  const copy = useCallback((text) => {
    navigator.clipboard?.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }, [])
  return [copied, copy]
}

// ── Result: table ──────────────────────────────────────────────────────────
function ResultTable({ rows, onExport }) {
  const [copied, copy] = useCopy()
  const [showAll, setShowAll] = useState(false)
  if (!rows?.length) return null
  const cols = Object.keys(rows[0]).filter((c) => c !== '_row_index')
  const numeric = new Set(cols.filter((c) => rows.slice(0, 20).every((r) => r[c] === null || r[c] === undefined || typeof r[c] === 'number')))
  const limit = showAll ? 200 : 12
  const visible = rows.slice(0, limit)

  const copyTable = () => {
    const header = cols.join('\t')
    const body = rows.map((r) => cols.map((c) => String(r[c] ?? '')).join('\t')).join('\n')
    copy(`${header}\n${body}`)
  }
  const fmt = (v) => (typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v))

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface-muted/60 px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
          <Table2 className="h-3.5 w-3.5" aria-hidden="true" />
          Result · {rows.length.toLocaleString()} {rows.length === 1 ? 'row' : 'rows'}
        </span>
        <div className="flex items-center gap-0.5">
          <button type="button" className="btn-ghost btn-sm h-7 px-2" onClick={copyTable}>
            {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          {onExport && (
            <>
              <button type="button" className="btn-ghost btn-sm h-7 px-2" onClick={() => onExport('csv')}>
                <Download className="h-3.5 w-3.5" aria-hidden="true" /> CSV
              </button>
              <button type="button" className="btn-ghost btn-sm h-7 px-2" onClick={() => onExport('xlsx')}>
                <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden="true" /> Excel
              </button>
            </>
          )}
        </div>
      </div>
      <div className="max-h-[360px] overflow-auto" tabIndex={0} role="region" aria-label="Result table">
        <table className="data-table">
          <thead>
            <tr>{cols.map((c) => <th key={c} scope="col" className={numeric.has(c) ? 'is-number' : undefined}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} title={String(row[c] ?? '')} className={numeric.has(c) ? 'is-number' : undefined}>
                    {row[c] === null || row[c] === undefined ? <span className="text-subtle">—</span> : fmt(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 12 && (
        <div className="flex items-center justify-between border-t border-line px-3 py-1.5 text-xs text-subtle">
          <span>Showing {visible.length.toLocaleString()} of {rows.length.toLocaleString()}</span>
          <button type="button" className="font-medium text-primary-text hover:underline" onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Show fewer' : `Show ${Math.min(rows.length, 200)} rows`}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Messages ───────────────────────────────────────────────────────────────
function StatusRow({ text }) {
  return (
    <div className="flex items-center gap-2.5 py-1 text-sm text-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin text-primary-text" aria-hidden="true" />
      <span>{text || 'Working on it…'}</span>
    </div>
  )
}

const SOURCE_LABEL = {
  engine: { text: 'Answered instantly', hint: "Tallis's question engine built this query without using AI." },
  cache: { text: 'Reused query', hint: 'This question was answered before; the same query ran on your current data.' },
  ai: {
    text: 'Used AI',
    hint: 'Your question, the column names and a few sample rows were sent to the AI service — never the whole file.',
    tone: 'badge-neutral',
    icon: Sparkles,
  },
}

function AiLabel({ ts, source }) {
  const badge = SOURCE_LABEL[source]
  return (
    <div className="mb-1.5 flex flex-wrap items-center gap-2">
      <LogoMark size={18} />
      <span className="text-sm font-semibold text-fg">Tallis</span>
      {ts && <time className="text-xs text-subtle" dateTime={ts}>{new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>}
      {badge && (() => {
        const Icon = badge.icon || Zap
        return (
          <span className={cx('badge', badge.tone || 'badge-success')} title={badge.hint}>
            <Icon className="h-3 w-3" aria-hidden="true" />{badge.text}
          </span>
        )
      })()}
    </div>
  )
}

function BotMessage({ msg, onAskFollowup, onRetry, canRetry }) {
  const { exportRows, exportReport, saveAnalysis } = useDataPilot()
  const [copied, copy] = useCopy()
  const [saveModalOpen, setSaveModalOpen] = useState(false)
  const [actionError, setActionError] = useState(null)

  if (msg.type === 'loading') {
    return (
      <div className="animate-fade-in">
        <AiLabel />
        <div className="space-y-2 pt-1" aria-label="Tallis is thinking" role="status">
          <div className="skeleton h-3.5 w-2/3" />
          <div className="skeleton h-3.5 w-1/2" />
        </div>
      </div>
    )
  }
  if (msg.type === 'status') {
    return (
      <div>
        <AiLabel />
        <StatusRow text={msg.content} />
      </div>
    )
  }

  const isError = msg.type === 'error' || !!msg.error
  const isStreaming = msg.type === 'streaming'

  const handleExportRows = async (format) => {
    setActionError(null)
    const result = await exportRows(
      msg.table_data,
      msg.metadata?.filename || `${msg.type || 'results'}_results`,
      format,
      { sql: msg.metadata?.sql, file_ids: msg.metadata?.dataset_refs },
    )
    if (!result?.success) setActionError(result?.error || `Couldn't export ${format.toUpperCase()}. Please try again.`)
  }

  const handleExportReport = async () => {
    setActionError(null)
    const result = await exportReport(
      msg.content,
      msg.metadata?.filename ? `${msg.metadata.filename}_${msg.type}` : `${msg.type || 'report'}`,
      'md',
    )
    if (!result?.success) setActionError(result?.error || "Couldn't download the brief. Please try again.")
  }

  return (
    <article className="group/bot animate-fade-in" aria-label="Tallis answer">
      <AiLabel ts={msg.ts} source={msg.metadata?.answered_by} />

      {msg.metadata?.reasoning && (
        <details className="mb-2 rounded-md border border-line text-sm">
          <summary className="cursor-pointer select-none px-3 py-2 font-medium text-muted hover:text-fg">Reasoning steps</summary>
          <div className="space-y-1 border-t border-line px-3 py-2 text-fg">
            {String(msg.metadata.reasoning).split('\n').filter(Boolean).map((step, i) => <p key={i}>{step}</p>)}
          </div>
        </details>
      )}

      {msg.content && (isError ? (
        <ErrorIntelligencePanel intelligentError={msg.metadata?.intelligent_error} fallbackMessage={msg.content} />
      ) : (
        <div className="prose-dp">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent(msg)}</ReactMarkdown>
          {isStreaming && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] bg-fg animate-caret" aria-hidden="true" />}
        </div>
      ))}

      {!isStreaming && (msg.chart_data || msg.table_data?.length > 0) && (
        <div className="mt-3 space-y-3">
          {msg.chart_data && (
            <div className="overflow-hidden rounded-lg border border-line bg-surface">
              <Suspense fallback={<div className="skeleton m-3 h-56" aria-label="Loading chart" />}>
                <ChartRenderer
                  spec={msg.chart_data}
                  onDataPointClick={(point) => onAskFollowup(`Investigate this data point: ${JSON.stringify(point)}`)}
                />
              </Suspense>
            </div>
          )}
          {msg.table_data?.length > 0 && !msg.chart_data && <ResultTable rows={msg.table_data} onExport={handleExportRows} />}
        </div>
      )}

      {!isStreaming && !isError && (msg.metadata?.explain || msg.metadata?.sql) && (
        <div className="mt-3"><ExplainPanel metadata={msg.metadata} /></div>
      )}

      {actionError && <p role="alert" className="mt-2 text-sm text-danger">{actionError}</p>}

      {!isStreaming && (msg.content || msg.table_data?.length > 0) && (
        <div className="mt-2 flex flex-wrap items-center gap-0.5 [@media(hover:hover)]:opacity-70 [@media(hover:hover)]:transition-opacity [@media(hover:hover)]:group-hover/bot:opacity-100 [@media(hover:hover)]:group-focus-within/bot:opacity-100">
          {msg.content && (
            <IconButton icon={copied ? Check : Copy} label={copied ? 'Copied' : 'Copy answer'} size="sm" onClick={() => copy(msg.content || '')} />
          )}
          {canRetry && <IconButton icon={RotateCcw} label="Ask again" size="sm" onClick={onRetry} />}
          {msg.table_data?.length > 0 && msg.chart_data && (
            <>
              <IconButton icon={Download} label="Export rows as CSV" size="sm" onClick={() => handleExportRows('csv')} />
              <IconButton icon={FileSpreadsheet} label="Export rows as Excel" size="sm" onClick={() => handleExportRows('xlsx')} />
            </>
          )}
          {msg.content && ['report', 'summary'].includes(msg.type) && (
            <button type="button" className="btn-ghost btn-sm" onClick={handleExportReport}>
              <Download className="h-3.5 w-3.5" aria-hidden="true" /> Download brief
            </button>
          )}
          {msg.content && !isError && (
            <button type="button" id={`save-analysis-btn-${msg.id}`} className="btn-ghost btn-sm" onClick={() => setSaveModalOpen(true)}>
              <Bookmark className="h-3.5 w-3.5" aria-hidden="true" /> Save
            </button>
          )}
        </div>
      )}

      {saveModalOpen && (
        <SaveAnalysisModal
          message={msg}
          onSave={async ({ title, type, tags }) => {
            const result = await saveAnalysis(msg, title, type, tags)
            if (!result.success) throw new Error(result.error || 'Save failed')
          }}
          onClose={() => setSaveModalOpen(false)}
        />
      )}
    </article>
  )
}

function UserMessage({ msg }) {
  return (
    <div className="flex justify-end animate-fade-in">
      <div className="flex max-w-[min(85%,640px)] flex-col items-end gap-1">
        <p className="message-user">{String(msg.content || '').replace(/^\[REASONING_MODE_ON\]\s*/, '')}</p>
        <time className="text-xs text-subtle" dateTime={msg.ts}>{new Date(msg.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
      </div>
    </div>
  )
}

// ── Empty states ───────────────────────────────────────────────────────────
const STARTERS = [
  { icon: Sigma, label: 'Summarize this data', text: 'Give me an executive summary of this data' },
  { icon: BarChart3, label: 'Compare categories', text: 'Show the top 10 rows by the main metric' },
  { icon: ListChecks, label: 'Check data quality', text: 'Check this data for quality issues and outliers' },
  { icon: LineChart, label: 'Forecast a trend', text: 'Forecast the next 3 months' },
]

const SUGGESTION_ICONS = { forecast: LineChart, visualize: BarChart3, clean: ListChecks, summary: Sigma, insight: Sparkles }

function EmptyConversation({ hasFiles, files, activeFileIds, suggestions, onPick }) {
  if (!hasFiles) {
    return (
      <div className="mx-auto w-full max-w-xl py-8 sm:py-14">
        <h2 className="text-2xl font-semibold text-fg">Ask questions about a spreadsheet</h2>
        <p className="mt-2 text-base text-muted">
          Upload a CSV or Excel file (or a PDF or Word file with tables) and ask in plain English — “Which region grew
          fastest last quarter?” Tallis runs the numbers on your data and shows how it got each answer.
        </p>
        <div className="mt-6">
          <FileUploader showFiles={false} />
        </div>
        <SampleDataButton className="mt-3" />
      </div>
    )
  }

  const active = files.filter((f) => activeFileIds.includes(f.file_id))
  const fromProfile = (suggestions || []).slice(0, 4).map((s) => ({
    icon: SUGGESTION_ICONS[s.type] || Sparkles, label: s.title, text: s.prompt, hint: s.description,
  }))
  const prompts = fromProfile.length ? fromProfile : STARTERS

  return (
    <div className="mx-auto w-full max-w-2xl py-8 sm:py-14">
      <h2 className="text-2xl font-semibold text-fg">What do you want to know?</h2>
      <p className="mt-2 text-base text-muted">
        {active.length
          ? <>Asking about <span className="font-medium text-fg">{active.map((f) => f.filename).join(', ')}</span>. Try one of these, or type your own question.</>
          : 'Select a dataset below the message box, then ask a question.'}
      </p>
      <ul className="mt-6 grid gap-2 sm:grid-cols-2">
        {prompts.map((p) => {
          const Icon = p.icon
          return (
            <li key={p.label}>
              <button
                type="button"
                onClick={() => onPick(p.text)}
                className="flex h-full w-full items-start gap-3 rounded-lg border border-line bg-surface p-3 text-left transition-colors hover:border-line-strong hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
              >
                <Icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary-text" aria-hidden="true" />
                <span className="min-w-0">
                  <span className="block text-base font-medium text-fg">{p.label}</span>
                  <span className="mt-0.5 line-clamp-2 block text-sm text-muted">{p.hint || p.text}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ── Composer ───────────────────────────────────────────────────────────────
function Composer({ inputRef, value, onChange, onSend, onStop, isStreaming, hasFiles, files, activeFileIds, toggleFileActive }) {
  const active = files.filter((f) => activeFileIds.includes(f.file_id))
  const inactive = files.filter((f) => !activeFileIds.includes(f.file_id))
  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef(null)

  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value, inputRef])

  useEffect(() => {
    if (!pickerOpen) return undefined
    const close = (e) => { if (pickerRef.current && !pickerRef.current.contains(e.target)) setPickerOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setPickerOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [pickerOpen])

  const canSend = value.trim().length > 0 && hasFiles

  return (
    <div className="pb-safe flex-shrink-0 border-t border-line bg-bg px-3 pb-3 pt-2 sm:px-6">
      <div className="mx-auto w-full max-w-3xl">
        <div className="rounded-xl border border-line bg-surface transition-colors focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/15">
          <label htmlFor="chat-input" className="sr-only">Ask a question about your data</label>
          <textarea
            ref={inputRef}
            id="chat-input"
            value={value}
            rows={1}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                if (!isStreaming) onSend()
              }
            }}
            placeholder={hasFiles ? 'Ask about your data, e.g. “Total revenue by region”' : 'Upload a spreadsheet to start asking questions'}
            disabled={!hasFiles}
            enterKeyHint="send"
            className="block max-h-[200px] w-full resize-none bg-transparent px-3.5 pb-1 pt-3 text-lg text-fg placeholder:text-subtle focus:outline-none disabled:cursor-not-allowed sm:text-base"
          />
          <div className="flex items-center gap-1 px-2 pb-2 pt-1">
            <IconButton icon={Paperclip} label="Upload a file" size="sm" tooltipSide="top" onClick={openUpload} />
            <div className="relative min-w-0" ref={pickerRef}>
              <button
                type="button"
                onClick={() => setPickerOpen((v) => !v)}
                disabled={!files.length}
                aria-expanded={pickerOpen}
                aria-haspopup="true"
                className="flex h-[30px] min-w-0 max-w-[180px] items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted hover:bg-ink/[0.06] hover:text-fg disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus sm:max-w-[280px]"
              >
                <Database className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                <span className="truncate">
                  {active.length === 0 ? 'No dataset selected' : active.length === 1 ? active[0].filename : `${active.length} datasets`}
                </span>
              </button>
              {pickerOpen && (
                <div className="absolute bottom-full left-0 z-30 mb-2 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-elevated p-1.5 shadow-float animate-pop-in">
                  <p className="px-2 pb-1 pt-1 text-xs text-subtle">Datasets used for answers</p>
                  {[...active, ...inactive].map((f) => (
                    <label key={f.file_id} className="flex cursor-pointer items-center gap-2.5 rounded px-2 py-2 hover:bg-ink/[0.05]">
                      <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--c-primary))]" checked={activeFileIds.includes(f.file_id)} onChange={() => toggleFileActive(f.file_id)} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-fg">{f.filename}</span>
                        <span className="block text-xs text-subtle">{f.row_count?.toLocaleString()} rows · {f.column_count} columns</span>
                      </span>
                    </label>
                  ))}
                  <button type="button" className="btn-ghost btn-sm mt-1 w-full justify-start" onClick={() => { setPickerOpen(false); openUpload() }}>
                    <Paperclip className="h-3.5 w-3.5" aria-hidden="true" /> Upload another file
                  </button>
                </div>
              )}
            </div>
            <div className="ml-auto flex items-center gap-2">
              <span className="hidden text-xs text-subtle lg:inline">Shift + Enter for a new line</span>
              {isStreaming ? (
                <button type="button" id="send-btn" onClick={onStop} className="btn-secondary btn-sm btn-icon h-9 w-9 rounded-full" aria-label="Stop generating">
                  <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
                </button>
              ) : (
                <button type="button" id="send-btn" onClick={onSend} disabled={!canSend} className="btn-primary btn-sm btn-icon h-9 w-9 rounded-full" aria-label="Send message">
                  <ArrowUp className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-1.5 hidden text-center text-xs text-subtle sm:block">Answers are computed from your data. Check the SQL under each answer before you share it.</p>
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function ChatWindow() {
  const location = useLocation()
  const {
    messages, isStreaming, sendMessage, cancelStream, clearMessages, files, activeFileIds, toggleFileActive,
    chatPromptInput, setChatPromptInput, suggestions, sessions, sessionId,
  } = useDataPilot()

  const inputRef = useRef(null)
  const scrollRef = useRef(null)
  const atBottomRef = useRef(true)
  const routedPromptRef = useRef(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [showJump, setShowJump] = useState(false)

  const hasFiles = files.length > 0
  const sessionName = sessions?.find((s) => s.session_id === sessionId)?.name

  // Follow new content only when the reader is already at the bottom.
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    atBottomRef.current = near
    setShowJump(!near)
  }
  const scrollToBottom = (smooth = true) => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }
  useLayoutEffect(() => {
    if (atBottomRef.current) scrollToBottom(false)
  }, [messages])

  useEffect(() => {
    const prompt = location.state?.suggestedPrompt
    if (!prompt || routedPromptRef.current === prompt) return
    routedPromptRef.current = prompt
    setChatPromptInput(prompt)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [location.state, setChatPromptInput])

  const send = (raw) => {
    const text = (raw ?? chatPromptInput).trim()
    if (!text || isStreaming || !hasFiles) return
    if (raw === undefined) setChatPromptInput('')
    atBottomRef.current = true
    sendMessage(text)
    inputRef.current?.focus()
  }

  const previousUserText = (index) => {
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') return messages[i].content
    }
    return null
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Conversation list */}
      <aside className="hidden w-[260px] flex-shrink-0 border-r border-line bg-surface xl:block" aria-label="Conversations">
        <SessionManager />
      </aside>
      {historyOpen && (
        <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true" aria-label="Conversations">
          <button type="button" className="absolute inset-0 h-full w-full cursor-default bg-black/40" aria-label="Close conversations" tabIndex={-1} onClick={() => setHistoryOpen(false)} />
          <div className="pt-safe absolute inset-y-0 left-0 flex w-[min(86vw,320px)] flex-col border-r border-line bg-surface shadow-dialog animate-slide-up">
            <div className="flex h-14 flex-shrink-0 items-center justify-between border-b border-line px-3">
              <span className="text-md font-semibold text-fg">Conversations</span>
              <IconButton icon={X} label="Close" tooltip={false} onClick={() => setHistoryOpen(false)} />
            </div>
            <div className="min-h-0 flex-1"><SessionManager onSelect={() => setHistoryOpen(false)} /></div>
          </div>
        </div>
      )}

      <section className="relative flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <div className="flex h-12 flex-shrink-0 items-center gap-2 border-b border-line px-3 sm:px-4">
          <IconButton icon={PanelLeft} label="Conversations" size="sm" className="xl:hidden" onClick={() => setHistoryOpen(true)} />
          <MessagesSquare className="hidden h-4 w-4 text-subtle xl:block" aria-hidden="true" />
          <h2 className="min-w-0 flex-1 truncate text-base font-medium text-fg">{sessionName || 'New conversation'}</h2>
          {messages.length > 0 && (
            <button
              type="button"
              id="clear-chat-btn"
              className="btn-ghost btn-sm"
              onClick={() => { if (window.confirm('Clear all messages in this conversation?')) clearMessages() }}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /><span className="hidden sm:inline">Clear</span>
            </button>
          )}
        </div>

        <SchemaWarnings />

        <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 sm:px-6" aria-busy={isStreaming}>
          {messages.length === 0 ? (
            <EmptyConversation
              hasFiles={hasFiles}
              files={files}
              activeFileIds={activeFileIds}
              suggestions={suggestions}
              onPick={(text) => send(text)}
            />
          ) : (
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 py-6" role="log" aria-live="polite" aria-relevant="additions">
              {messages.map((msg, index) => (msg.role === 'user'
                ? <UserMessage key={msg.id} msg={msg} />
                : (
                  <BotMessage
                    key={msg.id}
                    msg={msg}
                    onAskFollowup={(text) => send(text)}
                    canRetry={!isStreaming && !!previousUserText(index)}
                    onRetry={() => send(previousUserText(index))}
                  />
                )))}
            </div>
          )}
        </div>

        {showJump && messages.length > 0 && (
          <button
            type="button"
            onClick={() => { atBottomRef.current = true; scrollToBottom() }}
            className="absolute bottom-[132px] left-1/2 z-10 flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-elevated px-3 text-xs font-medium text-fg shadow-float"
          >
            <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" /> Latest
          </button>
        )}

        <Composer
          inputRef={inputRef}
          value={chatPromptInput}
          onChange={setChatPromptInput}
          onSend={() => send()}
          onStop={cancelStream}
          isStreaming={isStreaming}
          hasFiles={hasFiles}
          files={files}
          activeFileIds={activeFileIds}
          toggleFileActive={toggleFileActive}
        />
      </section>
    </div>
  )
}
