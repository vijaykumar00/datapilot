import { create } from 'zustand'
import { indexedDBHelper } from '../utils/indexedDBHelper'
import { apiUrl } from '../lib/apiConfig'

// ── Session & persistence helpers ─────────────────────────────────────────────
async function loadPersistedMessages(sessionId) {
  if (!sessionId) return []
  const msgs = await indexedDBHelper.get(`messages_${sessionId}`)
  return msgs || []
}

async function persistMessages(sessionId, messages) {
  if (!sessionId) return
  try {
    // Only keep last 100 messages; strip large table_data to save space
    const slim = messages.slice(-100).map(m => ({
      ...m,
      table_data: m.table_data?.length > 50 ? m.table_data.slice(0, 50) : m.table_data,
    }))
    await indexedDBHelper.set(`messages_${sessionId}`, slim)
  } catch (err) {
    console.error('Failed to persist messages:', err)
  }
}


async function apiFetch(path, options = {}) {
  const headers = { ...options.headers }
  
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('dp_access_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    const guestToken = sessionStorage.getItem('dp_guest_token')
    if (guestToken) {
      headers['X-Guest-Token'] = guestToken
    }
    const workspaceId = localStorage.getItem('dp_workspace_id')
    if (workspaceId) {
      headers['X-Workspace-ID'] = workspaceId
    }
  }

  const finalOptions = { ...options, headers }
  return fetch(apiUrl(path), finalOptions)
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
  activeFileId: null,
  messages: [],
  isStreaming: false,
  ollamaStatus: null,
  activeTab: 'chat',
  previewFileId: null,
  previewLoading: false,
  previewError: null,
  previewSaving: false,
  provider: 'gemini',
  providerOnline: false,
  sessionId: typeof window !== 'undefined' ? localStorage.getItem('datapilot_session_id') || '' : '',
  sessions: [],
  sessionsLoading: false,
  sessionsTotal: 0,
  sessionsHasMore: false,
  sessionsSearch: '',

  workspaceMode: 'chat',
  reasoningMode: false,
  attachmentList: [],
  templates: [],
  templatesLoading: false,
  templatesError: null,
  suggestions: [],
  savedAnalyses: [],
  savedAnalysesLoading: false,
  schemaWarnings: [],

  reports: [],
  reportsLoading: false,
  reportVersions: [],
  reportVersionsLoading: false,
  historyMessages: [],
  historyTotal: 0,
  historyLoading: false,
  datasetsList: [],
  datasetsLoading: false,

  chatPromptInput: '',
  setChatPromptInput: (val) => set({ chatPromptInput: val }),
  setActiveFileId: (fileId) => set({ activeFileId: fileId }),

  trackEvent: async (eventType, description) => {
    try {
      const workspaceId = localStorage.getItem('dp_workspace_id')
      await apiFetch('/user/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: eventType,
          description,
          workspace_id: workspaceId || null
        })
      })
    } catch (err) {
      console.warn('Failed to send tracking event:', err)
    }
  },

  uploadFile: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const resp = await apiFetch('/upload', { method: 'POST', body: form })
    const data = await resp.json()
    if (data.success) {
      // Build greeting message to inject into chat
      const greetingMsg = data.greeting
        ? {
            id: Date.now(),
            role: 'bot',
            content: data.greeting,
            type: 'text',
            ts: new Date().toISOString(),
            metadata: { type: 'greeting', file_id: data.file_id },
          }
        : null

      set(s => {
        const newMessages = greetingMsg
          ? [...s.messages, greetingMsg]
          : s.messages
        if (greetingMsg) persistMessages(s.sessionId, newMessages)
        return {
          files: [...s.files, data],
          activeFileIds: [...s.activeFileIds, data.file_id],
          activeFileId: s.activeFileId ?? data.file_id,
          previewFileId: s.previewFileId ?? data.file_id,
          suggestions: data.suggestions || [],
          schemaWarnings: data.schema_warnings || [],
          messages: newMessages,
          activeTab: 'chat',   // Switch to chat so user sees the greeting
        }
      })
      return { success: true, data }
    }
    return { success: false, error: data.error }
  },

  dismissSuggestion: (id) => {
    set(s => ({ suggestions: s.suggestions.filter(sg => sg.id !== id) }))
  },

  clearSuggestions: () => {
    set({ suggestions: [] })
  },

  dismissSchemaWarning: (key) => {
    // key = code + affected_column (see SchemaWarnings.jsx)
    set(s => ({
      schemaWarnings: s.schemaWarnings.filter(
        w => (w.code + (w.affected_column || '')) !== key
      ),
    }))
  },

  // ── Saved Analyses ────────────────────────────────────────────────────────
  loadSavedAnalyses: async (sessionId, fileId) => {
    set({ savedAnalysesLoading: true })
    try {
      const params = new URLSearchParams()
      if (sessionId) params.set('session_id', sessionId)
      if (fileId) params.set('file_id', fileId)
      const resp = await apiFetch(`/analyses?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        set({ savedAnalyses: data.analyses || [], savedAnalysesLoading: false })
        return { success: true, analyses: data.analyses }
      }
      throw new Error(data.error || 'Failed to load analyses')
    } catch (err) {
      set({ savedAnalysesLoading: false })
      return { success: false, error: err.message }
    }
  },

  saveAnalysis: async (msg, title, type, tags = []) => {
    const { sessionId, files } = get()
    const activeFile = files[0]
    try {
      const body = {
        session_id: sessionId,
        title,
        query: msg.userQuery || '',
        response: msg.content || '',
        type: type || msg.type || 'insight',
        chart_data: msg.chart_data || null,
        table_data: msg.table_data || null,
        metadata: msg.metadata || {},
        file_id: activeFile?.file_id || null,
        filename: activeFile?.filename || null,
        tags,
      }
      const resp = await apiFetch('/analyses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ savedAnalyses: [data.analysis, ...s.savedAnalyses] }))
        return { success: true, analysis: data.analysis }
      }
      throw new Error(data.error || 'Save failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  replayAnalysis: async (analysis) => {
    // Re-fire original query as a fresh AI message
    const { sendMessage } = get()
    if (analysis?.query) {
      await sendMessage(analysis.query)
    }
  },

  restoreAnalysis: (analysis) => {
    // Inject cached response into chat without hitting the AI
    const restoredMsg = {
      id: Date.now(),
      role: 'bot',
      content: analysis.response,
      type: analysis.type === 'chart' ? 'chart' : 'text',
      chart_data: analysis.chart_data || null,
      table_data: analysis.table_data || null,
      metadata: {
        ...(analysis.metadata || {}),
        restored_from: analysis.analysis_id,
        restore_title: analysis.title,
      },
      ts: new Date().toISOString(),
    }
    set(s => {
      const newMessages = [...s.messages, restoredMsg]
      persistMessages(s.sessionId, newMessages)
      return { messages: newMessages, activeTab: 'chat' }
    })
  },

  starAnalysis: async (analysisId, starred) => {
    try {
      const resp = await apiFetch(`/analyses/${analysisId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starred }),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          savedAnalyses: s.savedAnalyses
            .map(a => a.analysis_id === analysisId ? { ...a, starred } : a)
            .sort((a, b) => (b.starred ? 1 : 0) - (a.starred ? 1 : 0)),
        }))
        return { success: true }
      }
    } catch (err) {
      console.error('Failed to star analysis:', err)
    }
    return { success: false }
  },

  deleteSavedAnalysis: async (analysisId) => {
    try {
      await apiFetch(`/analyses/${analysisId}`, { method: 'DELETE' })
      set(s => ({ savedAnalyses: s.savedAnalyses.filter(a => a.analysis_id !== analysisId) }))
      return { success: true }
    } catch (err) {
      return { success: false, error: err.message }
    }
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
      persistMessages(s.sessionId, newMessages)
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

      if (!resp.ok) {
        let errMsg = 'Failed to connect to backend'
        let intelErr = null
        try {
          const errJson = await resp.json()
          errMsg = errJson.message || errJson.error || errMsg
          intelErr = errJson.intelligent_error || null
        } catch (_) {}
        throw { message: errMsg, intelligent_error: intelErr }
      }

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

            if (event.type === 'status') {
              set(s => ({
                messages: s.messages.map(m =>
                  m.id === botMsgId
                    ? { ...m, content: event.content, type: 'status' }
                    : m
                ),
              }))
            } else if (event.type === 'text_chunk') {
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
                persistMessages(s.sessionId, newMessages)
                return { messages: newMessages, isStreaming: false }
              })
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      const intel = err.intelligent_error || null
      const content = err.message || String(err)
      set(s => {
        const newMessages = s.messages.map(m =>
          m.id === botMsgId
            ? {
                ...m,
                content: content,
                type: 'error',
                metadata: {
                  ...m.metadata,
                  intelligent_error: intel,
                },
              }
            : m
        )
        persistMessages(s.sessionId, newMessages)
        return { messages: newMessages, isStreaming: false }
      })
    }
  },

  retryLastMessage: async () => {
    const { messages, sendMessage } = get()
    const lastUserIdx = messages.findLastIndex(m => m.role === 'user')
    if (lastUserIdx !== -1) {
      const lastUserMsg = messages[lastUserIdx]
      set(s => ({
        messages: s.messages.slice(0, lastUserIdx),
      }))
      await sendMessage(lastUserMsg.content)
    }
  },

  clearMessages: async () => {
    const { sessionId } = get()
    set({ messages: [] })
    if (sessionId) {
      await indexedDBHelper.delete(`messages_${sessionId}`)
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

  loadSessions: async (reset = false, searchVal = null) => {
    const limit = 20
    const currentSearch = searchVal !== null ? searchVal : get().sessionsSearch
    const currentOffset = reset ? 0 : get().sessions.length

    if (reset) {
      set({ sessionsLoading: true, sessionsSearch: currentSearch })
    } else {
      set({ sessionsLoading: true })
    }

    try {
      const params = new URLSearchParams()
      params.set('limit', limit)
      params.set('offset', currentOffset)
      if (currentSearch) {
        params.set('q', currentSearch)
      }

      const resp = await apiFetch(`/sessions?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        const newSessions = reset ? data.sessions : [...get().sessions, ...data.sessions]
        const uniqueSessions = []
        const seen = new Set()
        for (const s of newSessions) {
          if (!seen.has(s.session_id)) {
            seen.add(s.session_id)
            uniqueSessions.push(s)
          }
        }

        set({
          sessions: uniqueSessions,
          sessionsTotal: data.total,
          sessionsHasMore: uniqueSessions.length < data.total,
          sessionsLoading: false,
        })

        const currentId = get().sessionId
        const exists = uniqueSessions.some(s => s.session_id === currentId)
        if (exists && currentId) {
          const msgs = await loadPersistedMessages(currentId)
          set({ messages: msgs })
        } else {
          if (uniqueSessions.length > 0) {
            const firstSess = uniqueSessions[0].session_id
            set({ sessionId: firstSess })
            localStorage.setItem('datapilot_session_id', firstSess)
            const msgs = await loadPersistedMessages(firstSess)
            set({ messages: msgs })
          } else {
            await get().createSession()
          }
        }
      }
    } catch (err) {
      console.error('Failed to load sessions:', err)
      set({ sessionsLoading: false })
    }
  },

  createSession: async (name) => {
    const defaultName = name || `Analysis Session ${new Date().toLocaleDateString()}`
    try {
      const resp = await apiFetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: defaultName }),
      })
      const data = await resp.json()
      if (data.success) {
        const serverSessionId = data.session.session_id
        localStorage.setItem('datapilot_session_id', serverSessionId)
        set(s => ({
          sessionId: serverSessionId,
          messages: [],
          sessions: [data.session, ...s.sessions],
          sessionsTotal: s.sessionsTotal + 1,
        }))
        await persistMessages(serverSessionId, [])
        return { success: true, sessionId: serverSessionId }
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
      const localMsgs = await loadPersistedMessages(targetSessionId)
      if (localMsgs && localMsgs.length > 0) {
        set({ messages: localMsgs })
      } else {
        const resp = await apiFetch(`/sessions/${targetSessionId}/messages`)
        const data = await resp.json()
        if (data.success) {
          set({ messages: data.messages })
          await persistMessages(targetSessionId, data.messages)
        }
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
        await get().loadSessions(true)
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
          sessionsTotal: Math.max(0, s.sessionsTotal - 1),
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

  // ── Reports CRUD ────────────────────────────────────────────────────────────
  loadReports: async (filters = {}) => {
    set({ reportsLoading: true })
    try {
      const params = new URLSearchParams()
      if (filters.session_id) params.set('session_id', filters.session_id)
      if (filters.file_id) params.set('file_id', filters.file_id)
      if (filters.starred) params.set('starred', 'true')
      if (filters.report_type) params.set('report_type', filters.report_type)
      if (filters.limit) params.set('limit', filters.limit)
      const resp = await apiFetch(`/reports?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        set({ reports: data.reports, reportsLoading: false })
        return { success: true, reports: data.reports }
      }
      throw new Error(data.error || 'Failed to load reports')
    } catch (err) {
      set({ reportsLoading: false })
      return { success: false, error: err.message }
    }
  },

  saveReport: async (reportData) => {
    try {
      const resp = await apiFetch('/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reportData),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ reports: [data.report, ...s.reports] }))
        return { success: true, report: data.report }
      }
      throw new Error(data.error || 'Save failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  updateReport: async (reportId, updates) => {
    try {
      const resp = await apiFetch(`/reports/${reportId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          reports: s.reports.map(r => r.report_id === reportId ? { ...r, ...updates } : r)
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Update failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  deleteReport: async (reportId) => {
    try {
      const resp = await apiFetch(`/reports/${reportId}`, { method: 'DELETE' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({ reports: s.reports.filter(r => r.report_id !== reportId) }))
        return { success: true }
      }
      throw new Error(data.error || 'Delete failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  loadReportVersions: async (reportId) => {
    set({ reportVersionsLoading: true })
    try {
      const resp = await apiFetch(`/reports/${reportId}/versions`)
      const data = await resp.json()
      if (data.success) {
        set({ reportVersions: data.versions, reportVersionsLoading: false })
        return { success: true, versions: data.versions }
      }
      throw new Error(data.error || 'Failed to load versions')
    } catch (err) {
      set({ reportVersionsLoading: false })
      return { success: false, error: err.message }
    }
  },

  createReportVersion: async (reportId, versionData) => {
    try {
      const resp = await apiFetch(`/reports/${reportId}/version`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(versionData),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          reports: s.reports.map(r => r.report_id === reportId ? { ...r, ...data.report } : r)
        }))
        return { success: true, report: data.report }
      }
      throw new Error(data.error || 'Create version failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  // ── Query History CRUD ──────────────────────────────────────────────────────
  loadHistory: async (limit = 50, offset = 0) => {
    set({ historyLoading: true })
    try {
      const params = new URLSearchParams()
      params.set('limit', limit)
      params.set('offset', offset)
      const resp = await apiFetch(`/history?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        set({ historyMessages: data.messages, historyTotal: data.total, historyLoading: false })
        return { success: true, messages: data.messages, total: data.total }
      }
      throw new Error(data.error || 'Failed to load history')
    } catch (err) {
      set({ historyLoading: false })
      return { success: false, error: err.message }
    }
  },

  searchHistory: async (q, limit = 20) => {
    set({ historyLoading: true })
    try {
      const params = new URLSearchParams()
      params.set('q', q)
      params.set('limit', limit)
      const resp = await apiFetch(`/history/search?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        set({ historyMessages: data.messages, historyLoading: false })
        return { success: true, messages: data.messages }
      }
      throw new Error(data.error || 'Search failed')
    } catch (err) {
      set({ historyLoading: false })
      return { success: false, error: err.message }
    }
  },

  deleteHistoryItem: async (messageId) => {
    try {
      const resp = await apiFetch(`/history/${messageId}`, { method: 'DELETE' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          historyMessages: s.historyMessages.filter(m => m.id !== messageId),
          historyTotal: Math.max(0, s.historyTotal - 1),
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Delete failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  togglePinHistoryItem: async (messageId) => {
    try {
      const resp = await apiFetch(`/history/${messageId}/pin`, { method: 'POST' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          historyMessages: s.historyMessages.map(m => {
            if (m.id === messageId) {
              const meta = m.metadata || {}
              return { ...m, metadata: { ...meta, pinned: !meta.pinned } }
            }
            return m
          })
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Pin failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  // ── Dataset Management CRUD ─────────────────────────────────────────────────
  loadDatasets: async (filters = {}) => {
    set({ datasetsLoading: true })
    try {
      const params = new URLSearchParams()
      if (filters.archived !== undefined) {
        params.set('archived', String(filters.archived))
      }
      if (filters.session_id) params.set('session_id', filters.session_id)
      if (filters.tag) params.set('tag', filters.tag)
      const resp = await apiFetch(`/datasets?${params.toString()}`)
      const data = await resp.json()
      if (data.success) {
        set({ datasetsList: data.datasets, datasetsLoading: false })
        return { success: true, datasets: data.datasets }
      }
      throw new Error(data.error || 'Failed to load datasets')
    } catch (err) {
      set({ datasetsLoading: false })
      return { success: false, error: err.message }
    }
  },

  updateDataset: async (datasetId, updates) => {
    try {
      const resp = await apiFetch(`/datasets/${datasetId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          datasetsList: s.datasetsList.map(d => d.dataset_id === datasetId ? { ...d, ...updates } : d),
          files: s.files.map(f => {
            if (f.file_id === datasetId && updates.display_name) {
              return { ...f, filename: updates.display_name }
            }
            return f
          })
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Update failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  archiveDataset: async (datasetId) => {
    try {
      const resp = await apiFetch(`/datasets/${datasetId}/archive`, { method: 'POST' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          datasetsList: s.datasetsList.map(d => d.dataset_id === datasetId ? { ...d, archived: 1 } : d),
          files: s.files.filter(f => f.file_id !== datasetId)
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Archive failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  restoreDataset: async (datasetId) => {
    try {
      const resp = await apiFetch(`/datasets/${datasetId}/restore`, { method: 'POST' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          datasetsList: s.datasetsList.map(d => d.dataset_id === datasetId ? { ...d, archived: 0 } : d)
        }))
        const detailResp = await apiFetch(`/datasets/${datasetId}`)
        const detailData = await detailResp.json()
        if (detailData.success) {
          set(s => ({
            files: [...s.files, detailData.dataset]
          }))
        }
        return { success: true }
      }
      throw new Error(data.error || 'Restore failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },

  deleteDataset: async (datasetId) => {
    try {
      const resp = await apiFetch(`/files/${datasetId}`, { method: 'DELETE' })
      const data = await resp.json()
      if (data.success) {
        set(s => ({
          datasetsList: s.datasetsList.filter(d => d.dataset_id !== datasetId),
          files: s.files.filter(f => f.file_id !== datasetId),
          activeFileIds: s.activeFileIds.filter(id => id !== datasetId),
          previewFileId: s.previewFileId === datasetId ? null : s.previewFileId,
        }))
        return { success: true }
      }
      throw new Error(data.error || 'Delete failed')
    } catch (err) {
      return { success: false, error: err.message }
    }
  },
}))
