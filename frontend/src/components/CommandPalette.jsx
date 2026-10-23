/**
 * Command palette (Ctrl/Cmd + K): jump to any page, open a dataset or
 * conversation, upload, or switch theme.  Implements the ARIA combobox +
 * listbox pattern so it works with a keyboard and screen readers.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Check, CornerDownLeft, CreditCard, Database, MessageSquare, Moon, Search, Settings, Sun, Upload } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { NAV_GROUPS } from './shell/navigation'
import { setThemePreference } from '../lib/theme'
import { cx } from './ui'

export default function CommandPalette({ isOpen, onClose, onUpload }) {
  const navigate = useNavigate()
  const { files, activeFileIds, toggleFileActive, sessions, sessionId, switchSession, setPreviewFile } = useDataPilot()
  const [search, setSearch] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const listId = useId()

  useEffect(() => {
    if (isOpen) {
      setSearch('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [isOpen])

  const commands = useMemo(() => {
    const go = (to) => () => { navigate(to); onClose() }
    const list = []
    list.push({ group: 'Actions', label: 'Upload data', icon: Upload, hint: 'Ctrl U', action: () => { onClose(); onUpload?.() } })
    list.push({ group: 'Actions', label: 'Use light theme', icon: Sun, action: () => { setThemePreference('light'); onClose() } })
    list.push({ group: 'Actions', label: 'Use dark theme', icon: Moon, action: () => { setThemePreference('dark'); onClose() } })
    NAV_GROUPS.flatMap((g) => g.items).forEach((item) => list.push({ group: 'Go to', label: item.label, icon: item.icon, action: go(item.to) }))
    list.push({ group: 'Go to', label: 'Settings', icon: Settings, action: go('/app/settings/profile') })
    list.push({ group: 'Go to', label: 'Plan & billing', icon: CreditCard, action: go('/app/billing') })
    files.forEach((f) => {
      list.push({
        group: 'Datasets',
        label: f.filename,
        icon: Database,
        hint: activeFileIds.includes(f.file_id) ? 'In use' : null,
        action: () => {
          if (!activeFileIds.includes(f.file_id)) toggleFileActive(f.file_id)
          setPreviewFile?.(f.file_id)
          navigate('/app/spreadsheet')
          onClose()
        },
      })
    })
    ;(sessions || []).forEach((s) => {
      list.push({
        group: 'Conversations',
        label: s.name,
        icon: MessageSquare,
        active: s.session_id === sessionId,
        action: () => { switchSession(s.session_id); navigate('/app/analyze'); onClose() },
      })
    })
    return list
  }, [files, activeFileIds, sessions, sessionId, navigate, onClose, onUpload, toggleFileActive, switchSession, setPreviewFile])

  const q = search.trim().toLowerCase()
  const filtered = q ? commands.filter((c) => c.label.toLowerCase().includes(q) || c.group.toLowerCase().includes(q)) : commands

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${selectedIndex}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  if (!isOpen) return null

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIndex((i) => (filtered.length ? (i + 1) % filtered.length : 0)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIndex((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); filtered[selectedIndex]?.action() }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  let lastGroup = null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-3 pt-[10vh] animate-fade-in dark:bg-black/60" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full max-w-xl overflow-hidden rounded-xl border border-line bg-elevated shadow-dialog animate-pop-in" role="dialog" aria-modal="true" aria-label="Search and commands">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="h-4 w-4 flex-shrink-0 text-subtle" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={filtered[selectedIndex] ? `${listId}-${selectedIndex}` : undefined}
            aria-label="Search pages, datasets and conversations"
            placeholder="Search pages, datasets and conversations"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setSelectedIndex(0) }}
            onKeyDown={onKeyDown}
            className="h-12 flex-1 bg-transparent text-lg text-fg placeholder:text-subtle focus:outline-none sm:text-base"
          />
          <kbd className="kbd">Esc</kbd>
        </div>
        <ul ref={listRef} id={listId} role="listbox" aria-label="Results" className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5">
          {filtered.length === 0 ? (
            <li className="px-3 py-8 text-center text-sm text-muted">Nothing matches “{search}”.</li>
          ) : filtered.map((cmd, idx) => {
            const showGroup = cmd.group !== lastGroup
            lastGroup = cmd.group
            const Icon = cmd.icon
            const selected = idx === selectedIndex
            return (
              <li key={`${cmd.group}-${cmd.label}-${idx}`} role="presentation">
                {showGroup && <p className="px-2.5 pb-1 pt-2 text-xs font-medium text-subtle" role="presentation">{cmd.group}</p>}
                <div
                  id={`${listId}-${idx}`}
                  data-index={idx}
                  role="option"
                  aria-selected={selected}
                  onClick={cmd.action}
                  onMouseMove={() => setSelectedIndex(idx)}
                  className={cx('flex h-10 cursor-pointer items-center gap-3 rounded-md px-2.5 text-base', selected ? 'bg-primary-soft text-primary-text' : 'text-fg')}
                >
                  <Icon className="h-4 w-4 flex-shrink-0 opacity-80" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{cmd.label}</span>
                  {cmd.active && <Check className="h-4 w-4 text-success" aria-label="Current" />}
                  {cmd.hint && <span className="text-xs text-subtle">{cmd.hint}</span>}
                  {selected && <CornerDownLeft className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>,
    document.body,
  )
}
