import { create } from 'zustand'

// ── Session & persistence helpers ─────────────────────────────────────────────
function getOrCreateSessionId() {
  const key = 'datapilot_session_id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(key, id)
  }
  return id
}

function loadPersistedMessages() {
  try {
    const raw = localStorage.getItem('datapilot_messages')
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function persistMessages(messages) {
  try {
    // Only keep last 100 messages; strip large table_data to save space
    const slim = messages.slice(-100).map(m => ({
      ...m,
      table_data: m.table_data?.length > 50 ? m.table_data.slice(0, 50) : m.table_data,
    }))
    localStorage.setItem('datapilot_messages', JSON.stringify(slim))
  } catch {
    // quota exceeded – clear old messages
    localStorage.removeItem('datapilot_messages')
  }
}

const browserWindow = typeof window !== 'undefined' ? window : null
const API_HOST = browserWindow?.location?.hostname || '127.0.0.1'
const API_PORT = browserWindow?.__DATAPILOT_API_PORT__ || '8001'
const API_BASES = [
  '',
  `http://${API_HOST}:${API_PORT}`,
  `http://${API_HOST}:8001`,
  `http://${API_HOST}:8000`,
]

async function apiFetch(path, options = {}) {
  let lastError = null
  let lastResponse = null

  for (const base of API_BASES) {
    try {
      const response = await fetch(`${base}${path}`, options)
      if (response.status === 404 || response.status === 405) {
        lastResponse = response
        continue
      }
      return response
    } catch (error) {
      lastError = error
    }
  }

  if (lastResponse) {
    return lastResponse
  }
  throw lastError || new Error(`Request failed for ${path}`)
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function downloadResponse(resp, fallbackName) {
  if (!resp.ok) {
    let message = 'Download failed'
    try {
      const data = await resp.json()
      message = data.error || message
    } catch (_) {}
    throw new Error(message)
  }

  const blob = await resp.blob()
  const contentDisposition = resp.headers.get('content-disposition') || ''
  const match = contentDisposition.match(/filename="([^"]+)"/i)
  const filename = match?.[1] || fallbackName
  downloadBlob(blob, filename)
}

function normalizeColumns(columns = []) {
  return columns.map(col => (
    typeof col === 'string'
      ? { name: col, dtype: 'object', null_count: 0, unique_count: 0 }
      : col
  ))
}

function ensureIndexedRows(rows = []) {
  return rows.map((row, index) => (
    Object.prototype.hasOwnProperty.call(row, '_row_index')
      ? row
      : { ...row, _row_index: index }
  ))
}

function escapeCsv(value) {
  const text = String(value ?? '')
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

function exportRowsAsCsv(rows, filename) {
  const cleanRows = ensureIndexedRows(rows).map(({ _row_index, ...rest }) => rest)
  if (!cleanRows.length) {
    throw new Error('No preview rows available to export')
  }
  const headers = Object.keys(cleanRows[0])
  const lines = [
    headers.map(escapeCsv).join(','),
    ...cleanRows.map(row => headers.map(header => escapeCsv(row[header])).join(',')),
  ]
  downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }), filename)
}

function exportRowsAsExcel(rows, filename) {
  const cleanRows = ensureIndexedRows(rows).map(({ _row_index, ...rest }) => rest)
  if (!cleanRows.length) {
    throw new Error('No preview rows available to export')
  }
  const headers = Object.keys(cleanRows[0])
  const headerHtml = headers.map(header => `<th>${String(header)}</th>`).join('')
  const bodyHtml = cleanRows.map(row => (
    `<tr>${headers.map(header => `<td>${String(row[header] ?? '')}</td>`).join('')}</tr>`
  )).join('')
  const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></body></html>`
  downloadBlob(new Blob([html], { type: 'application/vnd.ms-excel' }), filename)
}

function hasEditablePreviewData(file) {
  return Boolean(
    file?.sample_data?.length &&
    file.sample_data.every(row => Object.prototype.hasOwnProperty.call(row, '_row_index'))
  )
}

export const useDataPilot = create((set, get) => ({
  files: [],
  activeFileIds: [],
  messages: loadPersistedMessages(),
  isStreaming: false,
  ollamaStatus: null,
  activeTab: 'chat',
  previewFileId: null,
  previewLoading: false,
  previewError: null,
  previewSaving: false,
  provider: 'gemini',
  providerOnline: false,
  sessionId: getOrCreateSessionId(),
  sessions: [],
  sessionsLoading: false,
  workspaceMode: 'chat',
  reasoningMode: false,
  attachmentList: [],
  templates: [],
  templatesLoading: false,
  templatesError: null,

  uploadFile: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await apiFetch('/upload', { method: 'POST', body: form })
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

  exportFile: async (fileId, format = 'csv') => {
    try {
      const file = get().files.find(f => f.file_id === fileId)
      const fallback = `${file?.filename || 'dataset'}.${format}`
      const resp = await apiFetch(`/export/file/${fileId}?format=${format}`)
      await downloadResponse(resp, fallback)
      return { success: true }
    } catch (err) {
      const file = get().files.find(f => f.file_id === fileId)
      if (file?.sample_data?.length) {
        try {
          const fallbackStem = (file.filename || 'dataset').replace(/\.[^.]+$/, '')
          if (format === 'csv') {
            exportRowsAsCsv(file.sample_data, `${fallbackStem}.csv`)
            return { success: true, fallback: 'local-csv' }
          }
          if (format === 'xlsx') {
            exportRowsAsExcel(file.sample_data, `${fallbackStem}.xls`)
            return { success: true, fallback: 'local-excel' }
          }
        } catch (fallbackErr) {
          return { success: false, error: fallbackErr.message }
        }
      }
      return { success: false, error: err.message }
    }
  },

  exportRows: async (rows, filename = 'results', format = 'csv') => {
    try {
      const resp = await apiFetch(`/export/results?format=${format}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows, filename }),
      })
      await downloadResponse(resp, `${filename}.${format}`)
      return { success: true }
    } catch (err) {
      try {
        if (format === 'csv') {
          exportRowsAsCsv(rows, `${filename}.csv`)
          return { success: true, fallback: 'local-csv' }
        }
        if (format === 'xlsx') {
          exportRowsAsExcel(rows, `${filename}.xls`)
          return { success: true, fallback: 'local-excel' }
        }
      } catch (fallbackErr) {
        return { success: false, error: fallbackErr.message }
      }
      return { success: false, error: err.message }
    }
  },

  exportReport: async (content, filename = 'report', format = 'md') => {
    try {
      const resp = await apiFetch(`/export/report?format=${format}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, filename }),
      })
      await downloadResponse(resp, `${filename}.${format}`)
      return { success: true }
    } catch (err) {
      try {
        const ext = format === 'txt' ? 'txt' : 'md'
        downloadBlob(new Blob([content], { type: 'text/plain;charset=utf-8' }), `${filename}.${ext}`)
        return { success: true, fallback: 'local-report' }
      } catch (fallbackErr) {
        return { success: false, error: fallbackErr.message }
      }
      return { success: false, error: err.message }
    }
  },

  loadPreviewFile: async (fileId) => {
    set({ previewLoading: true, previewError: null })
    try {
      const resp = await apiFetch(`/files/${fileId}`)
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
      const existing = get().files.find(f => f.file_id === fileId)
      if (existing?.sample_data?.length) {
        const fallbackFile = {
          ...existing,
          columns: normalizeColumns(existing.columns),
          sample_data: ensureIndexedRows(existing.sample_data),
        }
        set(s => ({
          files: s.files.map(f => (f.file_id === fileId ? fallbackFile : f)),
          previewFileId: fileId,
          previewLoading: false,
          previewError: null,
        }))
        return { success: true, data: fallbackFile, fallback: 'local-preview' }
      }
      set({
        previewFileId: fileId,
        previewLoading: false,
        previewError: err.message,
      })
      return { success: false, error: err.message }
    }
  },

  savePreviewEdits: async (fileId, edits) => {
    if (!edits.length) return { success: true }
    set({ previewSaving: true, previewError: null })
    try {
      const resp = await apiFetch(`/files/${fileId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edits }),
      })
      const data = await resp.json()
      if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to save edits')
      }
      set(s => ({
        files: s.files.map(f => (
          f.file_id === fileId
            ? { ...f, ...(data.preview || {}) }
            : f
        )),
        previewSaving: false,
        previewError: null,
      }))
      return { success: true, data }
    } catch (err) {
      set({ previewSaving: false, previewError: err.message })
      return { success: false, error: err.message }
    }
  },

  getTransformPreview: async (fileId, query) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/transform/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.error || 'Failed to generate transformation preview')
      }
      return data
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  applyStagedTransform: async (fileId, transformationId) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/transform/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transformation_id: transformationId }),
      })
      const data = await resp.json()
      if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to apply transformation')
      }
      set(s => ({
        files: s.files.map(f => (
          f.file_id === fileId
            ? { ...f, ...(data.preview || {}) }
            : f
        )),
      }))
      return data
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  undoLastTransform: async (fileId) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/transform/undo`, {
        method: 'POST',
      })
      const data = await resp.json()
      if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to undo last transformation')
      }
      set(s => ({
        files: s.files.map(f => (
          f.file_id === fileId
            ? { ...f, ...(data.preview || {}) }
            : f
        )),
      }))
      return data
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  generateBespokeReport: async (options) => {
    try {
      const resp = await apiFetch('/report/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.error || 'Failed to generate report')
      }
      return data
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  exportBespokeReport: async (options) => {
    try {
      const resp = await apiFetch('/report/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      })
      if (!resp.ok) {
        let message = 'Export failed'
        try {
          const data = await resp.json()
          message = data.error || message
        } catch (_) {}
        throw new Error(message)
      }
      const blob = await resp.blob()
      const ext = options.format || 'pdf'
      const filename = `${options.title || 'report'}.${ext}`
      downloadBlob(blob, filename)
      return { success: true }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  removeFile: async (fileId) => {
    await apiFetch(`/files/${fileId}`, { method: 'DELETE' })
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
    if (hasEditablePreviewData(existing)) {
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
      const resp = await apiFetch('/provider')
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
      const resp = await apiFetch('/provider', {
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

    set(s => {
      const newMessages = [...s.messages, userMsg, botMsg]
      persistMessages(newMessages)
      return { messages: newMessages, isStreaming: true }
    })

    try {
      const historyForApi = messages.slice(-10).map(m => ({
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content || '',
      }))

      const resp = await apiFetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          file_ids: activeFileIds,
          conversation_history: historyForApi,
          session_id: get().sessionId,
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
              set(s => {
                const newMessages = s.messages.map(m =>
                  m.id === botMsgId
                    ? {
                        ...m,
                        content: event.content ?? m.content ?? 'No response was returned.',
                        type: event.type || 'text',
                        chart_data: event.chart_data || null,
                        table_data: event.table_data || null,
                        metadata: event.metadata || {},
                        error: event.error || null,
                      }
                    : m
                )
                persistMessages(newMessages)
                return { messages: newMessages, isStreaming: false }
              })
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      set(s => {
        const newMessages = s.messages.map(m =>
          m.id === botMsgId
            ? { ...m, content: `Failed to connect to backend: ${err.message}`, type: 'error' }
            : m
        )
        persistMessages(newMessages)
        return { messages: newMessages, isStreaming: false }
      })
    }
  },

  clearMessages: async () => {
    const { sessionId } = get()
    set({ messages: [] })
    persistMessages([])
    if (sessionId) {
      try { await apiFetch(`/session/${sessionId}`, { method: 'DELETE' }) } catch (_) {}
    }
  },

  switchSheet: async (fileId, sheetName) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/sheet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sheet: sheetName }),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          files: s.files.map(f =>
            f.file_id === fileId
              ? { ...f, ...data, metadata: { ...f.metadata, active_sheet: sheetName } }
              : f
          ),
        }))
        // Refresh preview if this file is active
        if (get().previewFileId === fileId) {
          await get().loadPreviewFile(fileId)
        }
        return { success: true }
      }
      return { success: false, error: data.detail || 'Sheet switch failed' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  renameFile: async (fileId, newName) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: newName }),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          files: s.files.map(f =>
            f.file_id === fileId ? { ...f, filename: data.filename } : f
          ),
        }))
        return { success: true }
      }
      return { success: false, error: data.detail || 'Rename failed' }
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  checkOllama: async () => {
    try {
      const resp = await apiFetch('/provider')
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

  loadSessions: async () => {
    set({ sessionsLoading: true })
    try {
      const resp = await apiFetch('/sessions')
      const data = await resp.json()
      if (data.success) {
        set({ sessions: data.sessions })
        const currentId = get().sessionId
        const exists = data.sessions.some(s => s.session_id === currentId)
        if (!exists && currentId) {
          await apiFetch('/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: currentId, name: 'Active Session' }),
          })
          const reloadResp = await apiFetch('/sessions')
          const reloadData = await reloadResp.json()
          if (reloadData.success) {
            set({ sessions: reloadData.sessions })
          }
        }
      }
    } catch (err) {
      console.error('Failed to load sessions:', err)
    } finally {
      set({ sessionsLoading: false })
    }
  },

  createSession: async (name) => {
    const newId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const defaultName = name || `Analysis Session ${new Date().toLocaleDateString()}`
    try {
      const resp = await apiFetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: newId, name: defaultName }),
      })
      const data = await resp.json()
      if (data.success) {
        localStorage.setItem('datapilot_session_id', newId)
        set(s => ({
          sessionId: newId,
          messages: [],
          sessions: [data.session, ...s.sessions],
        }))
        persistMessages([])
        return { success: true, sessionId: newId }
      }
    } catch (err) {
      console.error('Failed to create session:', err)
    }
    return { success: false }
  },

  switchSession: async (targetSessionId) => {
    set({ sessionId: targetSessionId, previewLoading: true })
    localStorage.setItem('datapilot_session_id', targetSessionId)
    try {
      const resp = await apiFetch(`/sessions/${targetSessionId}/messages`)
      const data = await resp.json()
      if (data.success) {
        set({ messages: data.messages })
        persistMessages(data.messages)
      }
    } catch (err) {
      console.error('Failed to switch session:', err)
    } finally {
      set({ previewLoading: false })
    }
  },

  renameSession: async (targetSessionId, newName) => {
    try {
      const resp = await apiFetch(`/sessions/${targetSessionId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          sessions: s.sessions.map(sess =>
            sess.session_id === targetSessionId ? { ...sess, name: newName } : sess
          ),
        }))
        return { success: true }
      }
    } catch (err) {
      console.error('Failed to rename session:', err)
    }
    return { success: false }
  },

  togglePinSession: async (targetSessionId, currentPinned) => {
    const newPinned = !currentPinned
    try {
      const resp = await apiFetch(`/sessions/${targetSessionId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: newPinned }),
      })
      const data = await resp.json()
      if (data.success) {
        const reloadResp = await apiFetch('/sessions')
        const reloadData = await reloadResp.json()
        if (reloadData.success) {
          set({ sessions: reloadData.sessions })
        }
        return { success: true }
      }
    } catch (err) {
      console.error('Failed to toggle pin:', err)
    }
    return { success: false }
  },

  deleteSession: async (targetSessionId) => {
    try {
      const resp = await apiFetch(`/sessions/${targetSessionId}`, {
        method: 'DELETE',
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          sessions: s.sessions.filter(sess => sess.session_id !== targetSessionId),
        }))
        if (get().sessionId === targetSessionId) {
          const remaining = get().sessions
          if (remaining.length > 0) {
            await get().switchSession(remaining[0].session_id)
          } else {
            await get().createSession()
          }
        }
        return { success: true }
      }
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
    return { success: false }
  },

  setWorkspaceMode: (mode) => set({ workspaceMode: mode }),
  setReasoningMode: (enabled) => set({ reasoningMode: enabled }),
  setAttachmentList: (attachments) => set({ attachmentList: attachments }),

  loadTemplates: async () => {
    set({ templatesLoading: true, templatesError: null })
    try {
      const resp = await apiFetch('/templates')
      const data = await resp.json()
      if (data.success) {
        set({ templates: data.templates, templatesLoading: false })
        return { success: true, templates: data.templates }
      }
      throw new Error(data.error || 'Failed to load templates')
    } catch (err) {
      set({ templatesError: err.message, templatesLoading: false })
      return { success: false, error: err.message }
    }
  },

  saveCustomTemplate: async (options) => {
    try {
      const resp = await apiFetch('/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ templates: [...s.templates, data.template] }))
        return { success: true, template: data.template }
      }
      throw new Error(data.error || 'Failed to save template')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  duplicateTemplate: async (templateId) => {
    try {
      const resp = await apiFetch(`/templates/${templateId}/duplicate`, {
        method: 'POST',
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ templates: [...s.templates, data.template] }))
        return { success: true, template: data.template }
      }
      throw new Error(data.error || 'Failed to duplicate template')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  deleteTemplate: async (templateId) => {
    try {
      const resp = await apiFetch(`/templates/${templateId}`, {
        method: 'DELETE',
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ templates: s.templates.filter(t => t.template_id !== templateId) }))
        return { success: true }
      }
      throw new Error(data.error || 'Failed to delete template')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  runTemplateOnDataset: async (fileId, templateId, overrides = null) => {
    try {
      const resp = await apiFetch(`/files/${fileId}/transform/template/${templateId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mapping_overrides: overrides }),
      })
      
      const data = await resp.json()
      if (resp.status === 422) {
        return { success: false, error_type: 'column_mapping_required', ...data }
      }
      
      if (!resp.ok) {
        throw new Error(data.error || 'Failed to execute template')
      }
      
      if (data.status === 'completed' && data.preview) {
        set(s => ({
          files: s.files.map(f => (f.file_id === fileId ? { ...f, ...data.preview } : f)),
        }))
      }
      
      return data
    } catch (err) {
      return { success: false, error: err.message }
    }
  },
}))
