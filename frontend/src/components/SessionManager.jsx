import { useEffect, useState } from 'react'
import { Check, MessageSquarePlus, Pencil, Pin, PinOff, Search, Trash2, X } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { cx } from './ui'

/**
 * Conversation list: new chat, search, pinned and date groups, rename/pin/delete.
 * Rows are buttons (keyboard reachable); actions are always visible on touch.
 */
export default function SessionManager({ onSelect }) {
  const {
    sessions,
    sessionId,
    sessionsLoading,
    sessionsHasMore,
    sessionsTotal,
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

  // Debounced search that also handles initial mount load
  useEffect(() => {
    const timer = setTimeout(() => {
      loadSessions(true, search)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const handleCreate = async () => {
    await createSession()
    onSelect?.()
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
    if (window.confirm('Delete this conversation? This cannot be undone.')) {
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

  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
    // Trigger when scrolled to within 40px of bottom
    if (scrollHeight - scrollTop - clientHeight < 40) {
      if (!sessionsLoading && sessionsHasMore) {
        loadSessions(false)
      }
    }
  }

  const groupSessionsByDate = (sessList) => {
    const groups = {
      pinned: [],
      today: [],
      yesterday: [],
      last7Days: [],
      older: []
    }

    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const yesterdayStart = todayStart - 24 * 60 * 60 * 1000
    const sevenDaysAgoStart = todayStart - 6 * 24 * 60 * 60 * 1000

    sessList.forEach(session => {
      if (session.pinned) {
        groups.pinned.push(session)
        return
      }

      const dateStr = session.updated_at || session.created_at
      const dateObj = new Date(dateStr)
      const time = dateObj.getTime()

      if (time >= todayStart) {
        groups.today.push(session)
      } else if (time >= yesterdayStart) {
        groups.yesterday.push(session)
      } else if (time >= sevenDaysAgoStart) {
        groups.last7Days.push(session)
      } else {
        groups.older.push(session)
      }
    })

    return groups
  }

  const groups = groupSessionsByDate(sessions)

  const sections = [
    { key: 'pinned', title: 'Pinned' },
    { key: 'today', title: 'Today' },
    { key: 'yesterday', title: 'Yesterday' },
    { key: 'last7Days', title: 'Previous 7 days' },
    { key: 'older', title: 'Older' },
  ]

  const hasAnySessions = sessions.length > 0
  const iconBtn = 'flex h-7 w-7 items-center justify-center rounded text-subtle hover:bg-ink/[0.08] hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-shrink-0 flex-col gap-2 p-3">
        <button type="button" onClick={handleCreate} className="btn-secondary w-full justify-start">
          <MessageSquarePlus className="h-4 w-4" aria-hidden="true" /> New conversation
        </button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden="true" />
          <input
            type="search"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input h-9 min-h-0 py-0 pl-8 text-sm"
          />
        </div>
      </div>

      <div onScroll={handleScroll} className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {sessionsLoading && sessions.length === 0 ? (
          <div className="space-y-2 p-1" aria-label="Loading conversations">
            <div className="skeleton h-8 w-full" />
            <div className="skeleton h-8 w-4/5" />
            <div className="skeleton h-8 w-3/5" />
          </div>
        ) : !hasAnySessions ? (
          <p className="px-2 py-6 text-center text-sm text-subtle">
            {search ? 'No conversations match your search.' : 'Your conversations will appear here.'}
          </p>
        ) : (
          <>
            {sections.map((sec) => {
              const items = groups[sec.key]
              if (!items || items.length === 0) return null
              return (
                <div key={sec.key} className="mb-3">
                  <p className="px-2 pb-1 text-xs font-medium text-subtle">{sec.title}</p>
                  <ul className="space-y-0.5">
                    {items.map((s) => {
                      const isActive = s.session_id === sessionId
                      const isEditing = s.session_id === editingId
                      return (
                        <li key={s.session_id} className={cx('group relative flex items-center rounded-md', isActive ? 'bg-primary-soft' : 'hover:bg-ink/[0.05]')}>
                          {isEditing ? (
                            <div className="flex w-full items-center gap-1 p-1">
                              <input
                                type="text"
                                value={editName}
                                aria-label="Conversation name"
                                onChange={(e) => setEditName(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') handleSaveRename(e, s.session_id)
                                  if (e.key === 'Escape') handleCancelRename(e)
                                }}
                                autoFocus
                                className="input h-8 min-h-0 flex-1 py-0 text-sm"
                              />
                              <button type="button" className={iconBtn} onClick={(e) => handleSaveRename(e, s.session_id)} aria-label="Save name"><Check className="h-4 w-4" aria-hidden="true" /></button>
                              <button type="button" className={iconBtn} onClick={handleCancelRename} aria-label="Cancel rename"><X className="h-4 w-4" aria-hidden="true" /></button>
                            </div>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => { switchSession(s.session_id); onSelect?.() }}
                                aria-current={isActive ? 'true' : undefined}
                                className={cx(
                                  'min-w-0 flex-1 rounded-md px-2 py-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
                                  isActive ? 'text-primary-text' : 'text-fg',
                                )}
                              >
                                <span className="flex items-center gap-1.5 truncate text-sm font-medium">
                                  {s.pinned && <Pin className="h-3 w-3 flex-shrink-0 text-subtle" aria-label="Pinned" />}
                                  <span className="truncate">{s.name}</span>
                                </span>
                                <span className="block truncate text-xs text-subtle">{formatTime(s.updated_at || s.created_at)}</span>
                              </button>
                              <div className="flex flex-shrink-0 items-center pr-1 opacity-100 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-focus-within:opacity-100 [@media(hover:hover)]:group-hover:opacity-100">
                                <button type="button" className={iconBtn} onClick={(e) => handlePin(e, s)} aria-label={s.pinned ? `Unpin ${s.name}` : `Pin ${s.name}`}>
                                  {s.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Pin className="h-3.5 w-3.5" aria-hidden="true" />}
                                </button>
                                <button type="button" className={iconBtn} onClick={(e) => handleStartRename(e, s)} aria-label={`Rename ${s.name}`}>
                                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                                </button>
                                <button type="button" className={cx(iconBtn, 'hover:text-danger')} onClick={(e) => handleDelete(e, s.session_id)} aria-label={`Delete ${s.name}`}>
                                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                                </button>
                              </div>
                            </>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )
            })}
            {sessionsLoading && sessions.length > 0 && (
              <p className="py-2 text-center text-xs text-subtle" role="status">Loading more…</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
