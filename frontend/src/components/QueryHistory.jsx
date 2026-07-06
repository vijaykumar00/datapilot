import { useState, useEffect } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

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

export default function QueryHistory() {
  const {
    historyMessages,
    historyTotal,
    historyLoading,
    loadHistory,
    searchHistory,
    deleteHistoryItem,
    togglePinHistoryItem,
    sendMessage,
    setWorkspaceMode,
    setChatPromptInput,
  } = useDataPilot()

  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const limit = 20

  useEffect(() => {
    if (search.trim()) {
      searchHistory(search, 50)
    } else {
      loadHistory(limit, page * limit)
    }
  }, [search, page])

  const handleSearchChange = (e) => {
    setSearch(e.target.value)
    setPage(0)
  }

  const handleReplay = async (queryText) => {
    setWorkspaceMode('chat')
    setChatPromptInput(queryText)
    setTimeout(() => {
      sendMessage(queryText)
    }, 100)
  }

  const handleDuplicate = (queryText) => {
    setWorkspaceMode('chat')
    setChatPromptInput(queryText)
  }

  const handleTogglePin = async (msgId) => {
    await togglePinHistoryItem(msgId)
  }

  const handleDelete = async (msgId) => {
    if (confirm('Permanently delete this query pair from history?')) {
      await deleteHistoryItem(msgId)
    }
  }

  const totalPages = Math.ceil(historyTotal / limit)

  return (
    <div className="h-full flex flex-col bg-[#030712] animate-fade-in">
      {/* Header Panel */}
      <div className="px-6 py-4 border-b border-white/5 bg-[#070b14]/40 flex-shrink-0 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              📜 Audit Query History
            </h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Cross-session history of all database queries, analyses, and assistant reports
            </p>
          </div>
          <span className="text-[10px] bg-brand-500/10 text-brand-400 px-2 py-0.5 rounded-full font-mono border border-brand-500/20">
            Total Queries: {historyTotal}
          </span>
        </div>

        {/* Filter input */}
        <input
          type="text"
          placeholder="Search history by query text..."
          value={search}
          onChange={handleSearchChange}
          className="w-full bg-[#050811] border border-white/5 rounded-xl px-3.5 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/40 transition-all"
        />
      </div>

      {/* Feed list */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 custom-scrollbar min-h-0">
        {historyLoading ? (
          <div className="text-center py-12 text-slate-500 text-xs">Loading query logs...</div>
        ) : historyMessages.length === 0 ? (
          <div className="text-center py-16 text-slate-600 text-xs italic flex flex-col items-center gap-2">
            <span className="text-2xl">📜</span>
            <span>No query logs found</span>
          </div>
        ) : (
          historyMessages.map(item => {
            const isPinned = item.metadata?.pinned || false
            return (
              <div
                key={item.id}
                className={`glass p-4 rounded-xl border border-white/5 flex flex-col gap-3 relative group transition-all duration-300 hover:border-brand-500/25 ${
                  isPinned ? 'bg-amber-500/[0.01] border-amber-500/10' : ''
                }`}
              >
                {/* Header detail */}
                <div className="flex items-center justify-between text-[10px] text-slate-500">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-400 font-mono">
                      Session: {item.session_name || 'Active Session'}
                    </span>
                    <span>·</span>
                    <span>{formatRelativeTime(item.created_at)}</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleTogglePin(item.id)}
                      className={`text-xs ${isPinned ? 'text-amber-400' : 'text-slate-600 hover:text-amber-400'}`}
                      title={isPinned ? 'Unpin Query' : 'Pin Query'}
                    >
                      ★
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="text-xs text-slate-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity ml-1"
                      title="Delete log"
                    >
                      ✕
                    </button>
                  </div>
                </div>

                {/* Query details */}
                <div className="flex flex-col gap-2">
                  <div className="bg-white/5 border border-white/5 rounded-lg p-2.5 font-mono text-xs text-slate-200">
                    <span className="text-[10px] text-slate-500 font-semibold block mb-0.5">QUERY</span>
                    {item.content}
                  </div>

                  {item.response && (
                    <div className="bg-[#050811]/40 border border-white/5 rounded-lg p-3 text-xs text-slate-400 leading-relaxed font-medium">
                      <span className="text-[10px] text-slate-500 font-semibold block mb-1">REPLY</span>
                      {item.response.content?.slice(0, 300)}
                      {item.response.content?.length > 300 && '...'}
                    </div>
                  )}
                </div>

                {/* Action Dock */}
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => handleDuplicate(item.content)}
                    className="px-3 py-1 bg-white/5 border border-white/5 rounded-lg text-[10px] font-bold text-slate-300 hover:bg-white/10 transition-all"
                  >
                    👥 Duplicate / Edit
                  </button>
                  <button
                    onClick={() => handleReplay(item.content)}
                    className="px-3 py-1 bg-brand-600/10 border border-brand-500/20 rounded-lg text-[10px] font-bold text-brand-300 hover:bg-brand-500/20 transition-all"
                  >
                    ▶ Re-run
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Pagination Footer */}
      {!search.trim() && totalPages > 1 && (
        <div className="px-6 py-3 border-t border-white/5 flex items-center justify-between bg-[#070b14]/30 flex-shrink-0 text-xs text-slate-500 font-semibold">
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2.5 py-1 bg-white/5 rounded-lg text-slate-300 disabled:opacity-20"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="px-2.5 py-1 bg-white/5 rounded-lg text-slate-300 disabled:opacity-20"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
