import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useDataPilot } from '../hooks/useDataPilot'
import ChartRenderer from './ChartRenderer'

// ── Typing/Thinking Indicator ─────────────────────────────────────────────
function ThinkingIndicator({ text = 'Analyzing spreadsheet...' }) {
  return (
    <div className="flex gap-3 px-1.5 py-2 animate-pulse">
      <div className="w-7 h-7 rounded-xl flex items-center justify-center bg-brand-500/20 text-sm border border-brand-500/25 spin-slow">
        🧠
      </div>
      <div className="flex flex-col gap-1.5 flex-1 select-none">
        <span className="text-[11px] font-semibold text-brand-300 flex items-center gap-1.5">
          {text}
        </span>
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: '0s' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: '0.2s' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: '0.4s' }} />
        </div>
      </div>
    </div>
  )
}

// ── Skeleton message loader ────────────────────────────────────────────────
function SkeletonMessage() {
  return (
    <div className="flex gap-3 animate-fade-in py-2">
      <Avatar bot />
      <div className="flex flex-col gap-2.5 flex-1 max-w-[75%]">
        <div className="shimmer h-3.5 rounded-full w-2/3" />
        <div className="shimmer h-3.5 rounded-full w-1/2" />
        <div className="shimmer h-3.5 rounded-full w-5/6" />
      </div>
    </div>
  )
}

// ── Small interactive result table ────────────────────────────────────────
function InlineTable({ rows }) {
  if (!rows?.length) return null
  const cols = Object.keys(rows[0]).filter(c => c !== '_row_index')
  const [copied, setCopied] = useState(false)

  const handleCopyTable = () => {
    const headerRow = cols.join('\t')
    const dataRows = rows.map(r => cols.map(c => String(r[c] ?? '')).join('\t')).join('\n')
    navigator.clipboard.writeText(`${headerRow}\n${dataRows}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-white/5 bg-[#050811] max-h-64 flex flex-col relative group">
      {/* Table tools overlay */}
      <div className="absolute right-3.5 top-2.5 hidden group-hover:flex items-center gap-1 z-10 bg-[#0c101b]/80 backdrop-blur pl-1 rounded-md">
        <button
          onClick={handleCopyTable}
          className="text-[10px] bg-white/5 hover:bg-brand-500/20 text-slate-400 hover:text-brand-300 px-1.5 py-0.5 rounded border border-white/5 transition-colors"
        >
          {copied ? 'Copied ✓' : 'Copy Table'}
        </button>
      </div>

      <div className="overflow-auto custom-scrollbar flex-1">
        <table className="data-table">
          <thead>
            <tr>{cols.map(c => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.slice(0, 20).map((row, i) => (
              <tr key={i}>
                {cols.map(c => (
                  <td key={c} title={String(row[c] ?? '')}>
                    {row[c] === null || row[c] === undefined ? (
                      <span className="text-rose-500/50 italic text-[10px]">null</span>
                    ) : (
                      String(row[c])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 20 && (
        <p className="text-[10px] text-slate-500 px-3.5 py-2 border-t border-white/5 font-mono select-none">
          Showing 20 of {rows.length} rows (hover to copy table data)
        </p>
      )}
    </div>
  )
}

// ── Avatar (Compass / User Glyph) ─────────────────────────────────────────
function Avatar({ bot }) {
  return (
    <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-sm flex-shrink-0 mt-0.5 ${
      bot
        ? 'bg-gradient-to-br from-brand-600 to-purple-600 shadow-md border border-brand-500/20 glow-brand-sm'
        : 'bg-slate-800 border border-white/5'
    }`}>
      {bot ? '🧭' : '👤'}
    </div>
  )
}

// ── Status bubble trace ───────────────────────────────────────────────────
function StatusBubble({ content }) {
  return <ThinkingIndicator text={content} />
}

// ── Expandable AI Thoughts & Reasoning ────────────────────────────────────
function ReasoningCard({ content }) {
  const [expanded, setExpanded] = useState(false)

  if (!content) return null

  // Guess if this is reasoning text
  const cleanContent = content.trim()
  if (cleanContent.length < 5) return null

  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.01] overflow-hidden text-[11px]">
      <button
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between px-3.5 py-2 text-slate-500 hover:text-slate-300 hover:bg-white/[0.01] transition-all focus:outline-none"
      >
        <span className="font-semibold flex items-center gap-1.5 text-brand-400">
          🧠 AI Analytical Reasoning Steps
        </span>
        <span className="text-slate-600">{expanded ? 'Hide ✕' : 'Show ＋'}</span>
      </button>

      {expanded && (
        <div className="px-3.5 pb-3.5 pt-2 border-t border-white/5 bg-black/10 animate-fade-in font-sans leading-relaxed text-slate-300 space-y-1.5">
          {cleanContent.split('\n').map((step, idx) => (
            <p key={idx} className="flex gap-2 items-start">
              <span className="text-[10px] text-brand-400 leading-normal">✦</span>
              <span>{step}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

// ── AI Thought Process Trace ──────────────────────────────────────────────
function ThoughtProcess({ metadata }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  if (!metadata?.sql) return null

  const handleCopy = (e) => {
    e.stopPropagation()
    navigator.clipboard.writeText(metadata.sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Create list of line numbers
  const linesCount = metadata.sql.split('\n').length
  const lineNums = Array.from({ length: linesCount }, (_, i) => i + 1).join('\n')

  return (
    <div className="mt-1 rounded-xl border border-white/5 bg-white/[0.01] overflow-hidden text-[11px]">
      <button
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between px-3.5 py-2 text-slate-500 hover:text-slate-300 hover:bg-white/[0.01] transition-all focus:outline-none"
      >
        <span className="font-semibold flex items-center gap-1.5 text-brand-400">
          ⚙️ AI Thought Process & SQL Trace
        </span>
        <span className="text-slate-600">{expanded ? 'Hide ✕' : 'Show ＋'}</span>
      </button>

      {expanded && (
        <div className="px-3.5 pb-3.5 pt-2 border-t border-white/5 bg-[#050811] animate-fade-in space-y-2">
          {metadata.explanation && (
            <div className="px-1.5 pt-1">
              <span className="text-[9px] font-bold text-slate-500 tracking-wider uppercase block mb-0.5">
                Plain-English SQL Logic
              </span>
              <p className="text-slate-300 leading-relaxed font-sans">{metadata.explanation}</p>
            </div>
          )}

          {/* Monaco styled block */}
          <div className="editor-block">
            <div className="editor-header">
              <div className="flex items-center gap-1.5 text-[9px] font-bold text-slate-500 uppercase tracking-wider">
                <span>SQL Output</span>
                {metadata.row_count !== undefined && (
                  <span className="text-[8px] bg-brand-500/10 text-brand-300 px-1 py-0.2 rounded font-mono">
                    {metadata.row_count} rows
                  </span>
                )}
              </div>
              <button
                onClick={handleCopy}
                className="text-[9px] bg-white/5 hover:bg-brand-500/20 text-slate-400 hover:text-brand-300 px-1.5 py-0.5 rounded border border-white/5 transition-all"
              >
                {copied ? 'Copied ✓' : 'Copy'}
              </button>
            </div>
            <div className="editor-terminal custom-scrollbar">
              <div className="editor-lines">{lineNums}</div>
              <code className="editor-code">{metadata.sql}</code>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Bot message ───────────────────────────────────────────────────────────
function BotMessage({ msg, onAskFollowup }) {
  const { exportRows, exportReport, files, setPreviewFile } = useDataPilot()
  const [copiedResponse, setCopiedResponse] = useState(false)

  const handleExportRows = async (format) => {
    const result = await exportRows(
      msg.table_data,
      msg.metadata?.filename || `${msg.type || 'results'}_results`,
      format,
    )
    if (!result?.success) {
      window.alert(result?.error || `Failed to export ${format.toUpperCase()}`)
    }
  }

  const handleExportReport = async () => {
    const result = await exportReport(
      msg.content,
      msg.metadata?.filename
        ? `${msg.metadata.filename}_${msg.type}`
        : `${msg.type || 'report'}`,
      'md',
    )
    if (!result?.success) {
      window.alert(result?.error || 'Failed to export report')
    }
  }

  const handleCopyText = () => {
    navigator.clipboard.writeText(msg.content || '')
    setCopiedResponse(true)
    setTimeout(() => setCopiedResponse(false), 2000)
  }

  if (msg.type === 'loading') return <SkeletonMessage />
  if (msg.type === 'status') return <StatusBubble content={msg.content} />

  const isError = msg.type === 'error' || !!msg.error
  const reasoningSteps = msg.metadata?.reasoning || null

  return (
    <div className="flex gap-3 animate-slide-up group/bot relative py-2">
      <Avatar bot />
      <div className="flex flex-col gap-2 flex-1 min-w-0">
        
        {/* Reasoning traces first if present */}
        {reasoningSteps && (
          <ReasoningCard content={reasoningSteps} />
        )}

        {/* Text content card */}
        {msg.content && (
          <div className={`message-bot glass-sm px-4.5 py-3.5 border ${
            isError ? 'border-rose-500/20 bg-rose-900/5' : 'border-white/5'
          }`}>
            <div className="prose-dark">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Thought Process / SQL Trace */}
        <ThoughtProcess metadata={msg.metadata} />

        {/* Interactive Charts render */}
        {msg.chart_data && (
          <div className="mt-1 bg-[#050811] rounded-2xl border border-white/5 overflow-hidden">
            <ChartRenderer
              spec={msg.chart_data}
              onDataPointClick={(point) => onAskFollowup(`Investigate outlier data point: ${JSON.stringify(point)}`)}
            />
          </div>
        )}

        {/* Inline table result grids */}
        {msg.table_data?.length > 0 && !msg.chart_data && (
          <InlineTable rows={msg.table_data} />
        )}

        {/* Quick Actions Toolbar belt */}
        {((msg.table_data?.length > 0) || msg.content) && (
          <div className="flex flex-wrap gap-1.5 px-1 py-0.5 select-none opacity-80 group-hover/bot:opacity-100 transition-opacity">
            {files[0]?.file_id && (
              <button
                className="btn-ghost text-[10px]"
                onClick={() => setPreviewFile(files[0].file_id)}
              >
                🔍 Edit Grid
              </button>
            )}
            {msg.table_data?.length > 0 && (
              <>
                <button
                  className="btn-ghost text-[10px]"
                  onClick={() => handleExportRows('csv')}
                >
                  📥 Export CSV
                </button>
                <button
                  className="btn-ghost text-[10px]"
                  onClick={() => handleExportRows('xlsx')}
                >
                  📥 Export Excel
                </button>
              </>
            )}
            {msg.content && (
              <button
                className="btn-ghost text-[10px]"
                onClick={handleCopyText}
              >
                📋 {copiedResponse ? 'Copied! ✓' : 'Copy'}
              </button>
            )}
            {msg.content && ['report', 'summary'].includes(msg.type) && (
              <button
                className="btn-ghost text-[10px]"
                onClick={handleExportReport}
              >
                📖 Save Executive Brief
              </button>
            )}
          </div>
        )}

        {/* Timestamp footer indicator */}
        <span className="text-[9px] text-slate-600 px-1 Select-none">
          {new Date(msg.ts).toLocaleTimeString()}
        </span>
      </div>
    </div>
  )
}

// ── User message bubble ───────────────────────────────────────────────────
function UserMessage({ msg }) {
  return (
    <div className="flex gap-3 justify-end animate-slide-up py-1.5">
      <div className="flex flex-col items-end gap-1">
        <div className="message-user">{msg.content}</div>
        <span className="text-[9px] text-slate-600 select-none">{new Date(msg.ts).toLocaleTimeString()}</span>
      </div>
      <Avatar bot={false} />
    </div>
  )
}

// ── High conversion Suggested prompts suggestions chips ────────────────────
const QUICK_PROMPTS = [
  { label: '📊 Summarize Metric Data', text: 'Give me an executive summary of this data' },
  { label: '🧹 Scan Data Outliers', text: 'Check this data for quality issues and outliers' },
  { label: '📈 Analyze Main Columns', text: 'Show me the top 10 rows by the main metric' },
  { label: '🔮 Forecast Timeline Trends', text: 'Forecast the next 3 months' },
]

// ── Main ChatWindow Redesign ──────────────────────────────────────────────
export default function ChatWindow() {
  const {
    messages,
    isStreaming,
    sendMessage,
    clearMessages,
    files,
    activeFileIds,
    reasoningMode,
    setReasoningMode,
  } = useDataPilot()

  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    
    // Inject reasoning trigger prefix if reasoningMode is enabled
    const finalMsg = reasoningMode ? `[REASONING_MODE_ON] ${text}` : text
    sendMessage(finalMsg)
    
    // Reset heights
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
    inputRef.current?.focus()
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFollowup = (text) => {
    sendMessage(text)
  }

  const hasFiles = files.length > 0
  const activeCount = activeFileIds.length

  return (
    <div className="flex flex-col h-full bg-[#030712]">
      {/* Header bar banner */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 flex-shrink-0 bg-[#050811]/40 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-200">Conversational Workspace</span>
          {activeCount > 0 && (
            <span className="text-[10px] bg-brand-500/10 text-brand-300 px-2 py-0.5 rounded-full border border-brand-500/15 font-semibold">
              {activeCount} dataset{activeCount > 1 ? 's' : ''} active
            </span>
          )}
        </div>
        {messages.length > 0 && (
          <button
            id="clear-chat-btn"
            onClick={clearMessages}
            className="btn-ghost text-[10px]"
          >
            Clear History
          </button>
        )}
      </div>

      {/* Message Chat stream */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4 custom-scrollbar">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 animate-fade-in max-w-xl mx-auto py-12">
            <div className="text-center">
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center text-3xl shadow-xl border border-brand-500/20 bg-gradient-to-br from-brand-600 to-purple-600 mx-auto mb-4 animate-bounce">
                🧭
              </div>
              <h2 className="text-base font-black tracking-tight text-white mb-2">
                {hasFiles ? 'Conversational Analytics' : 'AI Spreadsheet Workspace'}
              </h2>
              <p className="text-xs text-slate-500 max-w-xs mx-auto leading-relaxed">
                {hasFiles
                  ? `Active datasets verified successfully. Enter questions naturally to profile, forecast, or generate interactive charts.`
                  : 'Start by uploading a CSV or Excel spreadsheet inside the left navigation sidebar.'}
              </p>
            </div>

            {hasFiles && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full mt-2 select-none">
                {QUICK_PROMPTS.map((p) => (
                  <button
                    key={p.label}
                    onClick={() => sendMessage(p.text)}
                    className="glass-sm px-3.5 py-3 text-left rounded-xl border border-white/5 text-slate-400 hover:text-brand-300 hover:border-brand-500/30 transition-all duration-200 hover:bg-brand-500/[0.03]"
                  >
                    <span className="text-[11px] font-semibold block mb-0.5">{p.label}</span>
                    <span className="text-[9px] text-slate-600 truncate block">{p.text}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((msg) =>
          msg.role === 'user'
            ? <UserMessage key={msg.id} msg={msg} />
            : <BotMessage key={msg.id} msg={msg} onAskFollowup={handleFollowup} />
        )}
        <div ref={bottomRef} />
      </div>

      {/* Premium Prompt box decking deck */}
      <div className="px-5 py-4 border-t border-white/5 bg-[#050811]/60 backdrop-blur-md flex-shrink-0">
        
        {/* Attachment Card Previews lists */}
        {activeFileIds.length > 0 && (
          <div className="flex gap-2 mb-3 flex-wrap select-none">
            {files
              .filter(f => activeFileIds.includes(f.file_id))
              .map(f => (
                <div key={f.file_id} className="glass-sm px-2.5 py-1 rounded-xl border border-brand-500/20 text-[10px] text-brand-300 flex items-center gap-1.5 animate-fade-in">
                  <span>📊</span>
                  <span className="font-semibold truncate max-w-[120px]">{f.filename}</span>
                  <span className="text-slate-600 font-mono text-[9px]">({f.row_count} rows)</span>
                </div>
              ))}
          </div>
        )}

        {/* Rounded Input Prompt deck */}
        <div className="glass p-1.5 rounded-2xl border border-white/5 hover:border-brand-500/25 focus-within:border-brand-500/35 focus-within:ring-4 focus-within:ring-brand-500/10 transition-all duration-300 bg-[#080d19]/80">
          <textarea
            ref={inputRef}
            id="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder={hasFiles ? 'Ask analytical questions, build charts, or run forecasts…' : 'Please upload a dataset first to begin chat analysis…'}
            disabled={isStreaming}
            rows={1}
            className="w-full bg-transparent border-0 resize-none text-xs text-slate-200 placeholder-slate-600 focus:outline-none px-3.5 py-2.5 max-h-32 custom-scrollbar"
            style={{ height: 'auto' }}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px'
            }}
          />
          
          {/* Deck Action buttons */}
          <div className="flex items-center justify-between px-2 pt-2 border-t border-white/5 select-none">
            <div className="flex items-center gap-1.5">
              
              {/* Deep Reasoning Toggle Switch */}
              <button
                onClick={() => setReasoningMode(!reasoningMode)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[9px] font-bold transition-all ${
                  reasoningMode
                    ? 'bg-brand-500/15 border-brand-500/30 text-brand-300'
                    : 'bg-white/5 border-transparent text-slate-500 hover:text-slate-300'
                }`}
                title="Reasoning logs outline"
              >
                🧠 Deep Reasoning
              </button>

              <span className="text-[10px] text-slate-600 font-mono pl-1 hidden sm:inline">
                Ctrl+K Command Menu
              </span>
            </div>

            <button
              id="send-btn"
              onClick={handleSend}
              disabled={!input.trim() || isStreaming}
              className="btn-primary w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center p-0 shadow-lg"
            >
              {isStreaming ? (
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <SendIcon />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SendIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <line x1="22" y1="2" x2="11" y2="13"/>
      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  )
}
