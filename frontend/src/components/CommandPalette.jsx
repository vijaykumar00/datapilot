import { useEffect, useRef, useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

export default function CommandPalette({ isOpen, onClose }) {
  const {
    activeTab,
    setActiveTab,
    files,
    activeFileIds,
    toggleFileActive,
    sessions,
    sessionId,
    switchSession,
    clearMessages,
    provider,
    switchProvider,
  } = useDataPilot()

  const [search, setSearch] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  // Hotkey listener inside parent or here
  useEffect(() => {
    if (isOpen) {
      setSearch('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  if (!isOpen) return null

  // Define commands list
  const commands = []

  // 1. Navigation
  commands.push({
    category: 'Navigation',
    label: 'Switch to Chat Tab',
    action: () => { setActiveTab('chat'); onClose() },
    shortcut: 'G C',
  })
  commands.push({
    category: 'Navigation',
    label: 'Switch to Data Preview Tab',
    action: () => { setActiveTab('preview'); onClose() },
    shortcut: 'G P',
  })

  // 2. Chat actions
  commands.push({
    category: 'Chat Actions',
    label: 'Clear Chat Messages',
    action: () => { if (confirm('Clear chat messages?')) clearMessages(); onClose() },
    shortcut: '⌥ ⌫',
  })

  // 3. Provider switching
  const providers = [
    { id: 'gemini', label: 'Gemini AI' },
    { id: 'claude', label: 'Claude AI' },
    { id: 'openai', label: 'OpenAI GPT' },
    { id: 'ollama', label: 'Ollama (Local)' },
  ]
  providers.forEach(p => {
    commands.push({
      category: 'LLM Provider',
      label: `Switch LLM to ${p.label}`,
      action: () => { switchProvider(p.id); onClose() },
      active: provider === p.id,
    })
  })

  // 4. File switching
  files.forEach(f => {
    const isActive = activeFileIds.includes(f.file_id)
    commands.push({
      category: 'Active Datasets',
      label: `Toggle File: ${f.filename}`,
      action: () => { toggleFileActive(f.file_id); onClose() },
      active: isActive,
    })
  })

  // 5. Sessions switching
  sessions.forEach(s => {
    const isActive = s.session_id === sessionId
    commands.push({
      category: 'Chat Sessions',
      label: `Load Session: ${s.name}`,
      action: () => { switchSession(s.session_id); onClose() },
      active: isActive,
    })
  })

  const filtered = commands.filter(cmd =>
    cmd.label.toLowerCase().includes(search.toLowerCase()) ||
    cmd.category.toLowerCase().includes(search.toLowerCase())
  )

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(idx => (idx + 1) % filtered.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(idx => (idx - 1 + filtered.length) % filtered.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[selectedIndex]) {
        filtered[selectedIndex].action()
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  // Ensure selected item is visible in scroll window
  useEffect(() => {
    const activeEl = listRef.current?.childNodes[selectedIndex]
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4 bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-2xl bg-[#0d1222] border border-white/10 shadow-2xl overflow-hidden glow-brand-lg"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/5 bg-[#0f1528]">
          <span className="text-base select-none">🔍</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a command or search datasets..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setSelectedIndex(0) }}
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 focus:outline-none"
          />
          <kbd className="px-2 py-0.5 text-[10px] bg-white/5 rounded border border-white/5 text-slate-500 font-mono">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div
          ref={listRef}
          className="max-h-[300px] overflow-y-auto custom-scrollbar py-2"
        >
          {filtered.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">
              No results found for &ldquo;{search}&rdquo;
            </p>
          ) : (
            filtered.map((cmd, idx) => {
              const isSelected = idx === selectedIndex
              return (
                <div
                  key={idx}
                  onClick={cmd.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex items-center justify-between px-4 py-2.5 cursor-pointer transition-all duration-150 select-none ${
                    isSelected
                      ? 'bg-brand-500/20 text-brand-300'
                      : 'text-slate-400 hover:text-slate-300'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded uppercase ${
                      isSelected ? 'bg-brand-500/30 text-brand-200' : 'bg-white/5 text-slate-500'
                    }`}>
                      {cmd.category}
                    </span>
                    <span className="text-xs font-medium truncate">{cmd.label}</span>
                    {cmd.active && (
                      <span className="text-[10px] text-emerald-500 font-semibold">✓</span>
                    )}
                  </div>

                  {cmd.shortcut && (
                    <kbd className="text-[10px] text-slate-600 font-mono">{cmd.shortcut}</kbd>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-white/5 bg-[#0b0e1b] text-[10px] text-slate-600 font-mono">
          <span>↑↓ to navigate</span>
          <span>↵ to select</span>
        </div>
      </div>
    </div>
  )
}
