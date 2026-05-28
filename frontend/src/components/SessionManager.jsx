import { useEffect, useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

export default function SessionManager() {
  const {
    sessions,
    sessionId,
    sessionsLoading,
    loadSessions,
    createSession,
    switchSession,
    renameSession,
    togglePinSession,
    deleteSession,
  } = useDataPilot()

  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editName, setEditName] = useState('')

  // Load sessions on mount
  useEffect(() => {
    loadSessions()
  }, [])

  const handleCreate = async () => {
    await createSession()
  }

  const handleStartRename = (e, s) => {
    e.stopPropagation()
    setEditingId(s.session_id)
    setEditName(s.name)
  }

  const handleSaveRename = async (e, id) => {
    e.stopPropagation()
    if (editName.trim()) {
      await renameSession(id, editName.trim())
    }
    setEditingId(null)
  }

  const handleCancelRename = (e) => {
    e.stopPropagation()
    setEditingId(null)
  }

  const handlePin = async (e, s) => {
    e.stopPropagation()
    await togglePinSession(s.session_id, s.pinned)
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to delete this chat session?')) {
      await deleteSession(id)
    }
  }

  const formatTime = (isoString) => {
    try {
      const date = new Date(isoString)
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch (_) {
      return ''
    }
  }

  const filteredSessions = sessions.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex flex-col gap-2 border-t border-white/5 pt-4 mt-4">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
          Saved Sessions
        </span>
        <button
          onClick={handleCreate}
          className="w-5 h-5 rounded-md flex items-center justify-center bg-white/5 hover:bg-brand-500/20 text-slate-400 hover:text-brand-300 transition-all border border-white/5 text-[10px] font-bold"
          title="New chat session"
        >
          ＋
        </button>
      </div>

      {/* Search */}
      <div className="relative px-1">
        <input
          type="text"
          placeholder="Search history..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full text-[11px] px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/5 text-slate-300 placeholder-slate-600 focus:outline-none focus:border-brand-500/30 transition-all"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-2 top-1.5 text-slate-600 hover:text-slate-400 text-xs"
          >
            ×
          </button>
        )}
      </div>

      {/* Sessions list */}
      <div className="space-y-1 max-h-[160px] overflow-y-auto custom-scrollbar px-1 py-0.5">
        {sessionsLoading && sessions.length === 0 ? (
          <div className="space-y-1.5 p-1 animate-pulse">
            <div className="h-7 bg-white/5 rounded-lg w-full" />
            <div className="h-7 bg-white/5 rounded-lg w-3/4" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <p className="text-[10px] text-slate-600 text-center py-4 italic">
            {search ? 'No matches found' : 'No saved sessions'}
          </p>
        ) : (
          filteredSessions.map((s) => {
            const isActive = s.session_id === sessionId
            const isEditing = s.session_id === editingId

            return (
              <div
                key={s.session_id}
                onClick={() => !isEditing && switchSession(s.session_id)}
                className={`group relative flex flex-col gap-0.5 px-2.5 py-2 rounded-lg cursor-pointer transition-all duration-200 border ${
                  isActive
                    ? 'bg-brand-500/10 border-brand-500/20 text-brand-300'
                    : 'bg-white/[0.02] hover:bg-white/5 border-transparent text-slate-400'
                }`}
              >
                {/* Session body */}
                <div className="flex items-center justify-between gap-1">
                  {isEditing ? (
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveRename(e, s.session_id)
                        if (e.key === 'Escape') handleCancelRename(e)
                      }}
                      autoFocus
                      className="flex-1 bg-[#101524] text-[11px] px-1.5 py-0.5 rounded border border-brand-500/40 text-slate-200 focus:outline-none"
                    />
                  ) : (
                    <span className="text-[11px] font-medium truncate pr-16 select-none">
                      {s.pinned && '📌 '}
                      {s.name}
                    </span>
                  )}

                  {/* Actions overlay (appears on hover) */}
                  {!isEditing && (
                    <div className="absolute right-2 top-2 hidden group-hover:flex items-center gap-1 bg-[#0a0f1e]/80 backdrop-blur-sm pl-1.5 py-0.5 rounded-md">
                      {/* Pin */}
                      <button
                        onClick={(e) => handlePin(e, s)}
                        className={`text-[10px] p-0.5 hover:bg-white/10 rounded transition-colors ${
                          s.pinned ? 'text-yellow-500' : 'text-slate-500 hover:text-slate-300'
                        }`}
                        title={s.pinned ? 'Unpin session' : 'Pin session'}
                      >
                        📌
                      </button>

                      {/* Rename */}
                      <button
                        onClick={(e) => handleStartRename(e, s)}
                        className="text-[10px] p-0.5 hover:bg-white/10 rounded text-slate-500 hover:text-slate-300 transition-colors"
                        title="Rename"
                      >
                        ✏️
                      </button>

                      {/* Delete */}
                      <button
                        onClick={(e) => handleDelete(e, s.session_id)}
                        className="text-[10px] p-0.5 hover:bg-red-500/20 rounded text-slate-500 hover:text-red-400 transition-colors"
                        title="Delete"
                      >
                        🗑️
                      </button>
                    </div>
                  )}

                  {/* Inline Save/Cancel for rename */}
                  {isEditing && (
                    <div className="flex items-center gap-0.5">
                      <button
                        onClick={(e) => handleSaveRename(e, s.session_id)}
                        className="text-[9px] px-1 bg-brand-600 hover:bg-brand-500 text-white rounded"
                      >
                        ✓
                      </button>
                      <button
                        onClick={handleCancelRename}
                        className="text-[9px] px-1 bg-white/5 hover:bg-white/10 text-slate-400 rounded"
                      >
                        ✕
                      </button>
                    </div>
                  )}
                </div>

                {/* Subtitle (Timestamp) */}
                {!isEditing && (
                  <span className="text-[9px] text-slate-600">
                    {formatTime(s.updated_at || s.created_at)}
                  </span>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
