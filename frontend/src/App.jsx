import { useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import DataPreview from './components/DataPreview'
import FileUploader from './components/FileUploader'
import { useDataPilot } from './hooks/useDataPilot'

// ── Ollama status indicator ───────────────────────────────────────────────
function OllamaStatus() {
  const { ollamaStatus, checkOllama } = useDataPilot()

  useEffect(() => {
    checkOllama()
    const interval = setInterval(checkOllama, 30_000)
    return () => clearInterval(interval)
  }, [])

  const online = ollamaStatus?.online
  const models = ollamaStatus?.models || []
  const model = models[0] || null

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg glass-sm text-xs">
      <div className={`status-dot ${online === undefined ? 'status-warn' : online ? 'status-online' : 'status-offline'}`} />
      <span className="text-slate-400">
        {online === undefined
          ? 'Checking Ollama…'
          : online
            ? model || 'Ollama online'
            : 'Ollama offline'}
      </span>
      {online && (
        <span className="text-[10px] text-emerald-500/70 font-mono">
          {models.length} model{models.length !== 1 ? 's' : ''}
        </span>
      )}
    </div>
  )
}

// ── Tab button ────────────────────────────────────────────────────────────
function TabBtn({ id, label, active, onClick }) {
  return (
    <button
      id={id}
      onClick={onClick}
      className={`flex-1 py-2 text-xs font-medium rounded-lg transition-all duration-200 ${
        active
          ? 'bg-brand-500/20 text-brand-300 border border-brand-500/30'
          : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
      }`}
    >
      {label}
    </button>
  )
}

// ── Layout ────────────────────────────────────────────────────────────────
export default function App() {
  const { activeTab, setActiveTab, files } = useDataPilot()

  return (
    <div className="noise flex h-screen overflow-hidden bg-[#0a0f1e]">
      {/* Ambient glow blobs */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute top-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full opacity-10"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)', filter: 'blur(60px)' }} />
        <div className="absolute bottom-[-10%] right-[-5%] w-[400px] h-[400px] rounded-full opacity-8"
          style={{ background: 'radial-gradient(circle, #a78bfa 0%, transparent 70%)', filter: 'blur(80px)' }} />
        <div className="absolute top-[40%] right-[30%] w-[300px] h-[300px] rounded-full opacity-5"
          style={{ background: 'radial-gradient(circle, #0ea5e9 0%, transparent 70%)', filter: 'blur(60px)' }} />
      </div>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="sidebar z-10">
        {/* Logo */}
        <div className="px-4 pt-5 pb-4 border-b border-white/5">
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center text-lg glow-brand-sm"
              style={{ background: 'linear-gradient(135deg, #4f46e5, #7c3aed)' }}>
              🧭
            </div>
            <div>
              <h1 className="text-sm font-bold gradient-text leading-none">DataPilot</h1>
              <p className="text-[10px] text-slate-600 mt-0.5">Local AI · Zero cloud</p>
            </div>
          </div>
        </div>

        {/* Ollama status */}
        <div className="px-3 pt-3 pb-1">
          <OllamaStatus />
        </div>

        {/* File uploader */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          <FileUploader />
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-white/5 text-center">
          <p className="text-[10px] text-slate-600">
            v1.0 · 100% local · no API keys
          </p>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-brand-600 hover:text-brand-400 transition-colors"
          >
            API docs →
          </a>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 z-10">
        {/* Tab bar */}
        <div className="flex items-center gap-2 px-4 pt-3 pb-2 border-b border-white/5 flex-shrink-0">
          <div className="flex gap-1 p-1 glass-sm rounded-xl flex-shrink-0">
            <TabBtn
              id="tab-chat"
              label="💬 Chat"
              active={activeTab === 'chat'}
              onClick={() => setActiveTab('chat')}
            />
            <TabBtn
              id="tab-preview"
              label="🔍 Preview"
              active={activeTab === 'preview'}
              onClick={() => setActiveTab('preview')}
            />
          </div>

          {files.length > 0 && (
            <div className="text-xs text-slate-500 flex items-center gap-1">
              <span className="text-brand-400 font-medium">{files.length}</span>
              file{files.length !== 1 ? 's' : ''} loaded
            </div>
          )}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden">
          <div className={`h-full ${activeTab === 'chat' ? 'block' : 'hidden'}`}>
            <ChatWindow />
          </div>
          <div className={`h-full ${activeTab === 'preview' ? 'block' : 'hidden'}`}>
            {files.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center gap-4 animate-fade-in">
                <div className="text-4xl">📂</div>
                <p className="text-slate-400 text-sm">Upload a file to preview its data here</p>
              </div>
            ) : (
              <DataPreview />
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
