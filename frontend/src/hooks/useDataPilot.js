import { create } from 'zustand'

const API_BASE = ''

export const useDataPilot = create((set, get) => ({
  files: [],
  activeFileIds: [],
  messages: [],
  isStreaming: false,
  ollamaStatus: null,
  activeTab: 'chat',
  previewFileId: null,
  previewLoading: false,
  previewError: null,
  provider: 'gemini',
  providerOnline: false,

  uploadFile: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form })
    const data = await resp.json()
    if (data.success) {
      set(s => ({
        files: [...s.files, data],
        activeFileIds: [...s.activeFileIds, data.file_id],
        previewFileId: s.previewFileId ?? data.file_id,
      }))
      return { success: true, data }
    }
    return { success: false, error: data.error }
  },

  loadPreviewFile: async (fileId) => {
    set({ previewLoading: true, previewError: null })
    try {
      const resp = await fetch(`${API_BASE}/files/${fileId}`)
      const data = await resp.json()
      if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to load preview')
      }

      set(s => ({
        files: s.files.map(f => (f.file_id === fileId ? { ...f, ...data } : f)),
        previewFileId: fileId,
        previewLoading: false,
        previewError: null,
      }))

      return { success: true, data }
    } catch (err) {
      set({
        previewFileId: fileId,
        previewLoading: false,
        previewError: err.message,
      })
      return { success: false, error: err.message }
    }
  },

  removeFile: async (fileId) => {
    await fetch(`${API_BASE}/files/${fileId}`, { method: 'DELETE' })
    set(s => ({
      files: s.files.filter(f => f.file_id !== fileId),
      activeFileIds: s.activeFileIds.filter(id => id !== fileId),
      previewFileId: s.previewFileId === fileId ? null : s.previewFileId,
      previewError: s.previewFileId === fileId ? null : s.previewError,
    }))
  },

  toggleFileActive: (fileId) => {
    set(s => ({
      activeFileIds: s.activeFileIds.includes(fileId)
        ? s.activeFileIds.filter(id => id !== fileId)
        : [...s.activeFileIds, fileId],
    }))
  },

  setPreviewFile: async (fileId) => {
    set({ activeTab: 'preview' })
    const existing = get().files.find(f => f.file_id === fileId)
    if (existing?.sample_data?.length) {
      set({ previewFileId: fileId, previewError: null, previewLoading: false })
      return { success: true, data: existing }
    }
    return get().loadPreviewFile(fileId)
  },

  setActiveTab: async (tab) => {
    set({ activeTab: tab })
    if (tab === 'preview') {
      const { previewFileId, files, setPreviewFile } = get()
      const targetId = previewFileId || files[0]?.file_id
      if (targetId) {
        await setPreviewFile(targetId)
      }
    }
  },

  checkProvider: async () => {
    try {
      const resp = await fetch(`${API_BASE}/provider`)
      const data = await resp.json()
      set({ provider: data.provider, providerOnline: data.online })
    } catch {
      set({ providerOnline: false })
    }
  },

  switchProvider: async (providerId, apiKey) => {
    try {
      const body = { provider: providerId }
      if (apiKey) body.api_key = apiKey
      const resp = await fetch(`${API_BASE}/provider`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.success) {
        set({ provider: data.provider, providerOnline: data.online })
      }
      return data
    } catch (err) {
      console.error('Provider switch failed:', err)
      return { success: false }
    }
  },

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
              set(s => ({
                messages: s.messages.map(m =>
                  m.id === botMsgId
                    ? { ...m, content: m.content + event.content, type: 'streaming' }
                    : m
                ),
              }))
            } else if (event.is_final) {
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

  checkOllama: async () => {
    try {
      const resp = await fetch(`${API_BASE}/provider`)
      const data = await resp.json()
      set({
        provider: data.provider,
        providerOnline: data.online,
        ollamaStatus: { online: data.online, models: [] },
      })
    } catch {
      set({ ollamaStatus: { online: false, models: [] }, providerOnline: false })
    }
  },
}))
