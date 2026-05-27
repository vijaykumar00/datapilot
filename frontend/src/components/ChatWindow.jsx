import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useDataPilot } from '../hooks/useDataPilot'
import ChartRenderer from './ChartRenderer'

// ── Typing indicator ──────────────────────────────────────────────────────
function TypingDots() {
  return (
    <div className="flex items-center gap-1.5 px-4 py-3">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  )
}

// ── Skeleton loader ───────────────────────────────────────────────────────
function SkeletonMessage() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <Avatar bot />
      <div className="flex flex-col gap-2 flex-1 max-w-[70%]">
        <div className="shimmer h-4 rounded-full w-3/4" />
        <div className="shimmer h-4 rounded-full w-1/2" />
        <div className="shimmer h-4 rounded-full w-5/6" />
      </div>
    </div>
  )
}

// ── Small result table ────────────────────────────────────────────────────
function InlineTable({ rows }) {
  if (!rows?.length) return null
  const cols = Object.keys(rows[0])
  const displayRows = rows.slice(0, 20)

  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-white/8 max-h-64 overflow-y-auto">
      <table className="data-table">
        <thead>
          <tr>{cols.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {displayRows.map((row, i) => (
            <tr key={i}>
              {cols.map(c => (
                <td key={c} title={String(row[c] ?? '')}>
                  {row[c] === null || row[c] === undefined ? <span className="text-slate-600 italic">null</span> : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 20 && (
        <p className="text-xs text-slate-500 px-3 py-2 border-t border-white/5">
          Showing 20 of {rows.length} rows
        </p>
      )}
    </div>
  )
}

// ── Avatar ────────────────────────────────────────────────────────────────
function Avatar({ bot }) {
  return (
    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm flex-shrink-0 mt-0.5 ${
      bot
        ? 'bg-gradient-to-br from-brand-600 to-purple-600 shadow-lg'
        : 'bg-gradient-to-br from-slate-600 to-slate-700'
    }`}>
      {bot ? '🧭' : '👤'}
    </div>
  )
}

// ── Status message ────────────────────────────────────────────────────────
function StatusBubble({ content }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500 px-2 animate-fade-in">
      <div className="w-3 h-3 border border-brand-500/50 border-t-transparent rounded-full"
        style={{ animation: 'spin 0.8s linear infinite' }} />
      {content}
    </div>
  )
}

// ── Bot message ───────────────────────────────────────────────────────────
function BotMessage({ msg, onAskFollowup }) {
  const { exportRows, exportReport, files, setPreviewFile } = useDataPilot()
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

  if (msg.type === 'loading') return <SkeletonMessage />
  if (msg.type === 'status') return <StatusBubble content={msg.content} />

  const isError = msg.type === 'error' || !!msg.error

  return (
    <div className="flex gap-3 animate-slide-up">
      <Avatar bot />
      <div className="flex flex-col gap-2 flex-1 min-w-0">
        {/* Text content */}
        {msg.content && (
          <div className={`message-bot glass-sm px-4 py-3 ${isError ? 'border-rose-500/30 bg-rose-900/10' : ''}`}>
            <div className="prose-dark">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Chart */}
        {msg.chart_data && (
          <div className="mt-1">
            <ChartRenderer
              spec={msg.chart_data}
              onDataPointClick={(point) => onAskFollowup(`Tell me more about: ${JSON.stringify(point)}`)}
            />
          </div>
        )}

        {/* Table data */}
        {msg.table_data?.length > 0 && !msg.chart_data && (
          <InlineTable rows={msg.table_data} />
        )}

        {((msg.table_data?.length > 0) || msg.content) && (
          <div className="flex flex-wrap gap-2 px-1">
            {files[0]?.file_id && (
              <button
                className="btn-ghost text-xs"
                onClick={() => setPreviewFile(files[0].file_id)}
              >
                Open editable preview
              </button>
            )}
            {msg.table_data?.length > 0 && (
              <>
                <button
                  className="btn-ghost text-xs"
                  onClick={() => handleExportRows('csv')}
                >
                  Download CSV
                </button>
                <button
                  className="btn-ghost text-xs"
                  onClick={() => handleExportRows('xlsx')}
                >
                  Download XLSX
                </button>
              </>
            )}
            {msg.content && ['report', 'summary'].includes(msg.type) && (
              <button
                className="btn-ghost text-xs"
                onClick={handleExportReport}
              >
                Export report
              </button>
            )}
          </div>
        )}

        {/* Timestamp */}
        <span className="text-[10px] text-slate-600 px-1">
          {new Date(msg.ts).toLocaleTimeString()}
        </span>
      </div>
    </div>
  )
}

// ── User message ──────────────────────────────────────────────────────────
function UserMessage({ msg }) {
  return (
    <div className="flex gap-3 justify-end animate-slide-up">
      <div className="flex flex-col items-end gap-1">
        <div className="message-user">{msg.content}</div>
        <span className="text-[10px] text-slate-600">{new Date(msg.ts).toLocaleTimeString()}</span>
      </div>
      <Avatar bot={false} />
    </div>
  )
}

// ── Quick prompts ─────────────────────────────────────────────────────────
const QUICK_PROMPTS = [
  { label: '📊 Summarize', text: 'Give me an executive summary of this data' },
  { label: '🧹 Clean data', text: 'Check this data for quality issues' },
  { label: '📈 Top values', text: 'Show me the top 10 rows by the main metric' },
  { label: '🔮 Forecast', text: 'Forecast the next 3 months' },
]

// ── Main ChatWindow ───────────────────────────────────────────────────────
export default function ChatWindow() {
  const { messages, isStreaming, sendMessage, clearMessages, files, activeFileIds } = useDataPilot()
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
    sendMessage(text)
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
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-200">Chat</span>
          {activeCount > 0 && (
            <span className="text-xs bg-brand-500/20 text-brand-300 px-2 py-0.5 rounded-full border border-brand-500/30">
              {activeCount} file{activeCount > 1 ? 's' : ''} active
            </span>
          )}
        </div>
        {messages.length > 0 && (
          <button
            id="clear-chat-btn"
            onClick={clearMessages}
            className="btn-ghost text-xs"
          >
            Clear
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 animate-fade-in">
            <div className="text-center">
              <div className="text-5xl mb-4">🧭</div>
              <h2 className="text-xl font-semibold gradient-text mb-2">
                {hasFiles ? 'What would you like to know?' : 'Welcome to DataPilot'}
              </h2>
              <p className="text-sm text-slate-500 max-w-xs">
                {hasFiles
                  ? `${activeCount} file(s) loaded. Ask anything about your data.`
                  : 'Upload a CSV or Excel file to get started with AI-powered analysis.'}
              </p>
            </div>

            {hasFiles && (
              <div className="grid grid-cols-2 gap-2 w-full max-w-md">
                {QUICK_PROMPTS.map((p) => (
                  <button
                    key={p.label}
                    id={`quick-${p.label.replace(/\s+/g, '-').toLowerCase()}`}
                    onClick={() => sendMessage(p.text)}
                    className="glass-sm px-3 py-2.5 text-left text-xs text-slate-300 hover:text-slate-100
                      hover:border-brand-500/40 transition-all duration-200 hover:bg-brand-500/5"
                  >
                    {p.label}
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

      {/* Input */}
      <div className="px-4 py-3 border-t border-white/5">
        {/* Active file pills */}
        {activeFileIds.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {files
              .filter(f => activeFileIds.includes(f.file_id))
              .map(f => (
                <span key={f.file_id}
                  className="text-[10px] bg-brand-900/40 text-brand-300 border border-brand-500/20 px-2 py-0.5 rounded-full">
                  📄 {f.filename}
                </span>
              ))}
          </div>
        )}

        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            id="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder={hasFiles ? 'Ask anything about your data…' : 'Upload a file first…'}
            disabled={isStreaming}
            rows={1}
            className="input-dark resize-none flex-1 min-h-[44px] max-h-32"
            style={{ height: 'auto' }}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px'
            }}
          />
          <button
            id="send-btn"
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="btn-primary h-11 px-4 flex-shrink-0"
          >
            {isStreaming ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
                style={{ animation: 'spin 0.8s linear infinite' }} />
            ) : (
              <SendIcon />
            )}
          </button>
        </div>
        <p className="text-[10px] text-slate-600 mt-1.5 px-1">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="22" y1="2" x2="11" y2="13"/>
      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  )
}
