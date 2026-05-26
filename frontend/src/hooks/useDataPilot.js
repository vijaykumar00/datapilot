import { create } from 'zustand'

const API_BASE = ''  // proxied via Vite

export const useDataPilot = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────────────────
  files: [],               // [{file_id, filename, row_count, column_count, columns, uploaded_at}]
  activeFileIds: [],       // file_ids selected for current chat
  messages: [],            // [{id, role, content, type, chart_data, table_data, metadata, ts}]
  isStreaming: false,
  ollamaStatus: null,      // {online, models}
  activeTab: 'chat',       // 'chat' | 'preview'
  previewFileId: null,

  // ── File actions ────────────────────────────────────────────────────────
  uploadFile: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form })
    const data = await resp.json()
    if (data.success) {
      set(s => ({
        files: [...s.files, data],
        activeFileIds: [...s.activeFileIds, data.file_id],
      }))
      return { success: true, data }
    }
    return { success: false, error: data.error }
  },

  removeFile: async (fileId) => {
    await fetch(`${API_BASE}/files/${fileId}`, { method: 'DELETE' })
    set(s => ({
      files: s.files.filter(f => f.file_id !== fileId),
      activeFileIds: s.activeFileIds.filter(id => id !== fileId),
      previewFileId: s.previewFileId === fileId ? null : s.previewFileId,
    }))
  },

  toggleFileActive: (fileId) => {
    set(s => ({
      activeFileIds: s.activeFileIds.includes(fileId)
        ? s.activeFileIds.filter(id => id !== fileId)
        : [...s.activeFileIds, fileId],
    }))
  },

  setPreviewFile: (fileId) => set({ previewFileId: fileId, activeTab: 'preview' }),

  setActiveTab: (tab) => set({ activeTab: tab }),

  // ── Chat actions ────────────────────────────────────────────────────────
  sendMessage: async (text) => {
    const { activeFileIds, messages } = get()

    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: text,
      type: 'text',
      ts: new Date().toISOString(),
    }

    const botMsgId = Date.now() + 1
    const botMsg = {
      id: botMsgId,
      role: 'bot',
      content: '',
      type: 'loading',
      ts: new Date().toISOString(),
    }

    set(s => ({ messages: [...s.messages, userMsg, botMsg], isStreaming: true }))

    try {
      const historyForApi = messages.slice(-10).map(m => ({
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content || '',
      }))

      const resp = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          file_ids: activeFileIds,
          conversation_history: historyForApi,
        }),
      })

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))

            if (event.type === 'text_chunk') {
              // Streaming tokens
              set(s => ({
                messages: s.messages.map(m =>
                  m.id === botMsgId
                    ? { ...m, content: m.content + event.content, type: 'streaming' }
                    : m
                ),
              }))
            } else if (event.is_final) {
              // Final message with full data
              set(s => ({
                messages: s.messages.map(m =>
                  m.id === botMsgId
                    ? {
                        ...m,
                        content: event.content || m.content,
                        type: event.type || 'text',
                        chart_data: event.chart_data || null,
                        table_data: event.table_data || null,
                        metadata: event.metadata || {},
                        error: event.error || null,
                      }
                    : m
                ),
                isStreaming: false,
              }))
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      set(s => ({
        messages: s.messages.map(m =>
          m.id === botMsgId
            ? { ...m, content: `Failed to connect to backend: ${err.message}`, type: 'error' }
            : m
        ),
        isStreaming: false,
      }))
    }
  },

  clearMessages: () => set({ messages: [] }),

  // ── Ollama status ───────────────────────────────────────────────────────
  checkOllama: async () => {
    try {
      const resp = await fetch(`${API_BASE}/ollama/status`)
      const data = await resp.json()
      set({ ollamaStatus: data })
    } catch {
      set({ ollamaStatus: { online: false, models: [] } })
    }
  },
}))
