import { useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import DataPreview from './components/DataPreview'
import FileUploader from './components/FileUploader'
import ProviderSelector from './components/ProviderSelector'
import StepIndicator from './components/StepIndicator'
import SessionManager from './components/SessionManager'
import CommandPalette from './components/CommandPalette'
import ChartRenderer from './components/ChartRenderer'
import SavedAnalyses from './components/SavedAnalyses'
import SavedReports from './components/SavedReports'
import QueryHistory from './components/QueryHistory'
import DatasetManager from './components/DatasetManager'
import { useDataPilot } from './hooks/useDataPilot'
import ReactMarkdown from 'react-markdown'

// ── Ollama status indicator ───────────────────────────────────────────────
function AIStatus() {
  const { provider, providerOnline, checkOllama } = useDataPilot()

  useEffect(() => {
    checkOllama()
    const interval = setInterval(checkOllama, 30_000)
    return () => clearInterval(interval)
  }, [])

  const icons = { gemini: '✨', openai: '🤖', claude: '🎭', ollama: '❄️' }
  const labels = { gemini: 'Gemini', openai: 'OpenAI', claude: 'Claude', ollama: 'Ollama' }

  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-xl glass-sm text-[10px] border border-white/5">
      <div className="flex items-center gap-2">
        <div className={`status-dot ${providerOnline === undefined ? 'status-warn' : providerOnline ? 'status-online' : 'status-offline'}`} />
        <span className="text-slate-400 font-medium">
          {icons[provider] || '🧠'} {labels[provider] || provider}
        </span>
      </div>
      {providerOnline && (
        <span className="text-[9px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded font-mono">active</span>
      )}
    </div>
  )
}

// ── Dashboard View Sub-Component ──────────────────────────────────────────
function DashboardView() {
  const { files, activeFileId, messages, switchSheet, loadPreviewFile } = useDataPilot()
  const charts = messages.filter(m => m.chart_data)
  const activeFile = files.find(f => f.file_id === activeFileId) || files[0] || null
  
  const insights = activeFile?.metadata?.insights || []
  const sheets = activeFile?.metadata?.sheet_names || []
  const activeSheet = activeFile?.metadata?.active_sheet || null
  
  const [activeCategory, setActiveCategory] = useState('all')
  const [showSqlCardId, setShowSqlCardId] = useState(null)
  const [copiedCardId, setCopiedCardId] = useState(null)
  const [isRegenerating, setIsRegenerating] = useState(false)

  const handleSheetChange = async (sheetName) => {
    if (!activeFile) return
    await switchSheet(activeFile.file_id, sheetName)
  }

  const handleRegenerate = async () => {
    if (!activeFile) return
    setIsRegenerating(true)
    if (activeSheet) {
      await switchSheet(activeFile.file_id, activeSheet)
    } else {
      await loadPreviewFile(activeFile.file_id)
    }
    setIsRegenerating(false)
  }

  const handleCopySql = (id, sqlText) => {
    navigator.clipboard.writeText(sqlText)
    setCopiedCardId(id)
    setTimeout(() => setCopiedCardId(null), 2000)
  }

  // Filter insights by category
  const filteredInsights = activeCategory === 'all'
    ? insights
    : insights.filter(i => i?.type === activeCategory)

  // Calculate alert counts
  const anomaliesCount = insights.filter(i => i?.severity === 'warning' || i?.severity === 'error').length

  const categories = [
    { id: 'all', label: 'All', icon: '✨' },
    { id: 'statistical', label: 'Statistical', icon: '🔢' },
    { id: 'trend', label: 'Trend', icon: '📈' },
    { id: 'quality', label: 'Quality', icon: '⚠️' },
    { id: 'forecast', label: 'Forecast', icon: '🔮' },
    { id: 'relationship', label: 'Relationship', icon: '🔗' },
  ]

  const getSeverityStyle = (severity) => {
    switch (severity) {
      case 'error':
        return {
          border: 'border-rose-500/20 hover:border-rose-500/40',
          bg: 'bg-[#1e1114]/30',
          text: 'text-rose-400',
          dot: 'bg-rose-500',
          glow: 'shadow-[0_0_15px_-3px_rgba(244,63,94,0.1)]',
          icon: '❌'
        }
      case 'warning':
        return {
          border: 'border-amber-500/20 hover:border-amber-500/40',
          bg: 'bg-[#1e1711]/30',
          text: 'text-amber-400',
          dot: 'bg-amber-500',
          glow: 'shadow-[0_0_15px_-3px_rgba(245,158,11,0.1)]',
          icon: '⚠️'
        }
      case 'success':
        return {
          border: 'border-emerald-500/20 hover:border-emerald-500/40',
          bg: 'bg-[#111e15]/30',
          text: 'text-emerald-400',
          dot: 'bg-emerald-500',
          glow: 'shadow-[0_0_15px_-3px_rgba(16,185,129,0.1)]',
          icon: '⚡'
        }
      case 'info':
      default:
        return {
          border: 'border-cyan-500/20 hover:border-cyan-500/40',
          bg: 'bg-[#111b1e]/30',
          text: 'text-cyan-400',
          dot: 'bg-cyan-500',
          glow: 'shadow-[0_0_15px_-3px_rgba(6,182,212,0.1)]',
          icon: '✦'
        }
    }
  }

  const getCategoryIcon = (type) => {
    switch (type) {
      case 'statistical': return '🔢'
      case 'trend': return '📈'
      case 'quality': return '⚠️'
      case 'forecast': return '🔮'
      case 'relationship': return '🔗'
      default: return '💡'
    }
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-6 custom-scrollbar animate-fade-in bg-[#030712]">
      {/* 1. Header Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 pb-4 bg-[#030712]/50 backdrop-blur sticky top-0 z-10">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            📊 Auto Insights Control Center
          </h2>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Real-time proactive data profiling, metrics diagnostics, and anomaly warnings.
          </p>
        </div>

        {activeFile && (
          <div className="flex items-center gap-2 flex-wrap">
            {/* Dataset Selector */}
            {files.length > 1 && (
              <div className="flex items-center gap-1.5 bg-white/5 border border-white/5 rounded-xl px-2.5 py-1 text-xs">
                <span className="text-slate-500">Dataset:</span>
                <select
                  value={activeFileId || activeFile.file_id}
                  onChange={(e) => useDataPilot.getState().setActiveFileId(e.target.value)}
                  className="bg-transparent text-slate-200 border-none outline-none cursor-pointer font-semibold py-0.5 focus:ring-0"
                >
                  {files.map(f => (
                    <option key={f.file_id} value={f.file_id} className="bg-[#0b0f19] text-slate-200">{f.filename}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Sheet Selector (Excel only) */}
            {sheets.length > 1 && (
              <div className="flex items-center gap-1.5 bg-white/5 border border-white/5 rounded-xl px-2.5 py-1 text-xs">
                <span className="text-slate-500">Sheet:</span>
                <select
                  value={activeSheet || sheets[0]}
                  onChange={(e) => handleSheetChange(e.target.value)}
                  className="bg-transparent text-slate-200 border-none outline-none cursor-pointer font-semibold py-0.5 focus:ring-0"
                >
                  {sheets.map(sh => (
                    <option key={sh} value={sh} className="bg-[#0b0f19] text-slate-200">{sh}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Manual Regenerate Button */}
            <button
              onClick={handleRegenerate}
              disabled={isRegenerating}
              className="btn-ghost flex items-center gap-1.5 text-[10px] h-8 bg-white/5 border border-white/5 font-semibold text-slate-300 hover:bg-white/10"
            >
              {isRegenerating ? (
                <>
                  <div className="w-3 h-3 border border-slate-300 border-t-transparent rounded-full animate-spin" />
                  Regenerating...
                </>
              ) : (
                <>🔄 Profile Dataset</>
              )}
            </button>
          </div>
        )}
      </div>

      {/* 2. KPI Metrics Grid */}
      {activeFile ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="glass px-4.5 py-4 rounded-xl border border-white/5 relative overflow-hidden group hover:border-brand-500/35 transition-all duration-300">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Total Rows Loaded</span>
            <span className="text-xl font-black text-brand-300 font-mono mt-1.5 block">
              {activeFile.row_count?.toLocaleString() || 0}
            </span>
            <div className="absolute right-3.5 top-3.5 text-base opacity-30 select-none">📋</div>
          </div>
          <div className="glass px-4.5 py-4 rounded-xl border border-white/5 relative overflow-hidden group hover:border-brand-500/35 transition-all duration-300">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Total Columns</span>
            <span className="text-xl font-black text-emerald-400 font-mono mt-1.5 block">
              {activeFile.column_count || 0}
            </span>
            <div className="absolute right-3.5 top-3.5 text-base opacity-30 select-none">📊</div>
          </div>
          <div className="glass px-4.5 py-4 rounded-xl border border-white/5 relative overflow-hidden group hover:border-brand-500/35 transition-all duration-300">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Quality Anomalies</span>
            <span className="text-xl font-black text-amber-400 font-mono mt-1.5 block">
              {anomaliesCount}
            </span>
            <div className="absolute right-3.5 top-3.5 text-base opacity-30 select-none">⚠️</div>
          </div>
          <div className="glass px-4.5 py-4 rounded-xl border border-white/5 relative overflow-hidden group hover:border-brand-500/35 transition-all duration-300">
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Visual Chart Blocks</span>
            <span className="text-xl font-black text-blue-400 font-mono mt-1.5 block">
              {charts.length}
            </span>
            <div className="absolute right-3.5 top-3.5 text-base opacity-30 select-none">📈</div>
          </div>
        </div>
      ) : (
        <div className="glass-sm rounded-xl p-5 text-center text-slate-500 text-xs italic border border-white/5 bg-white/[0.01]">
          Upload a CSV or Excel spreadsheet to compile analytics.
        </div>
      )}

      {/* 3. Horizontal Tabbed Insights Feed & Anomaly Banner */}
      {activeFile && (
        <div className="space-y-4">
          {/* Anomaly banner if duplicates or errors exist */}
          {anomaliesCount > 0 && (
            <div className="glass bg-amber-500/[0.02] border border-amber-500/10 rounded-2xl p-4 flex gap-3.5 items-start">
              <span className="text-lg leading-none">⚠️</span>
              <div className="space-y-0.5">
                <h4 className="text-xs font-bold text-amber-400">Data Quality Alerts Outstanding</h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  We identified {anomaliesCount} data anomalies (duplicate records, extreme outliers, or null clusters) that could skew statistical summaries. Review cards below or run quality cleaner in chat workspace.
                </p>
              </div>
            </div>
          )}

          {/* Glassmorphic Tabs toolbar */}
          <div className="flex items-center gap-1.5 overflow-x-auto border-b border-white/5 pb-2 flex-shrink-0 custom-scrollbar select-none">
            {categories.map(cat => {
              const count = cat.id === 'all'
                ? insights.length
                : insights.filter(i => i?.type === cat.id).length
              return (
                <button
                  key={cat.id}
                  onClick={() => { setActiveCategory(cat.id); setShowSqlCardId(null) }}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-semibold border transition-all duration-300 flex-shrink-0 ${
                    activeCategory === cat.id
                      ? 'bg-brand-500/10 border-brand-500/35 text-brand-300 shadow-[0_0_10px_-2px_rgba(99,102,241,0.2)]'
                      : 'bg-white/5 border-white/5 text-slate-400 hover:bg-white/10 hover:border-white/10 hover:text-slate-200'
                  }`}
                >
                  <span>{cat.icon}</span>
                  <span>{cat.label}</span>
                  <span className="font-mono text-[9px] bg-white/5 text-slate-500 px-1.5 py-0.5 rounded-md font-bold">
                    {count}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Cards Feed */}
          {filteredInsights.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredInsights.map((insight, idx) => {
                const isObj = insight && typeof insight === 'object'
                const id = isObj ? (insight.id || `idx_${idx}`) : `str_${idx}`
                const type = isObj ? (insight.type || 'statistical') : 'statistical'
                const titleText = isObj ? (insight.title || '') : insight
                const descriptionText = isObj ? (insight.description || '') : ''
                const severity = isObj ? (insight.severity || 'info') : 'info'
                const metric = isObj ? (insight.metric || '') : ''
                const sqlText = isObj ? (insight.sql || '') : ''
                const chartType = isObj ? (insight.chart_type || '') : ''
                
                const style = getSeverityStyle(severity)
                const isSqlOpen = showSqlCardId === id
                const isCopied = copiedCardId === id

                return (
                  <div
                    key={id}
                    className={`glass border rounded-2xl p-4.5 flex flex-col gap-3 transition-all duration-300 relative group overflow-hidden ${style.border} ${style.bg} ${style.glow}`}
                  >
                    {/* Glowing highlight strip */}
                    <div className={`absolute top-0 left-0 w-1.5 h-full ${style.dot}`} />

                    {/* Card Header */}
                    <div className="flex items-start justify-between gap-3 pl-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs" title={type}>
                          {getCategoryIcon(type)}
                        </span>
                        <span className={`text-[10px] font-bold uppercase tracking-wider ${style.text}`}>
                          {type}
                        </span>
                        <div className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                      </div>
                      
                      {metric && (
                        <div className="bg-white/5 border border-white/5 rounded-lg px-2 py-0.5 font-mono text-[9px] font-bold text-slate-200 flex items-center justify-center">
                          {metric}
                        </div>
                      )}
                    </div>

                    {/* Card Content */}
                    <div className="pl-2.5 space-y-2 select-text">
                      <h3 className="text-xs font-bold text-slate-100 leading-snug group-hover:text-slate-50 transition-colors">
                        {titleText}
                      </h3>
                      
                      {descriptionText && (
                        <p className="text-[11px] text-slate-400 leading-relaxed font-medium">
                          {descriptionText}
                        </p>
                      )}
                    </div>

                    {/* Expandable/Collapsible SQL block wrapper */}
                    {sqlText && (
                      <div className="pl-2.5 mt-1 border-t border-white/[0.03] pt-3 flex flex-col gap-2">
                        <div className="flex items-center justify-between">
                          <button
                            onClick={() => setShowSqlCardId(isSqlOpen ? null : id)}
                            className="text-[9px] font-bold text-brand-400 hover:text-brand-300 transition-colors flex items-center gap-1 font-mono uppercase tracking-wider"
                          >
                            {isSqlOpen ? '▲ Hide verification SQL' : '▼ View verification SQL'}
                          </button>

                          {chartType && (
                            <span className="text-[8px] bg-slate-800/40 text-slate-400 px-1.5 py-0.5 rounded font-semibold font-mono">
                              📊 Recommended: {chartType}
                            </span>
                          )}
                        </div>

                        {isSqlOpen && (
                          <div className="relative rounded-xl border border-white/5 overflow-hidden bg-[#050811] text-[10px] font-mono p-3 leading-relaxed text-emerald-400 animate-fade-in max-h-48 overflow-y-auto custom-scrollbar select-text select-all">
                            <div className="absolute right-2 top-2 flex items-center z-10">
                              <button
                                onClick={() => handleCopySql(id, sqlText)}
                                className={`px-2 py-1 rounded text-[8px] font-mono font-bold tracking-wider uppercase border transition-all ${
                                  isCopied
                                    ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                                    : 'bg-white/5 border-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
                                }`}
                              >
                                {isCopied ? 'Copied' : 'Copy'}
                              </button>
                            </div>
                            <pre className="pr-12 whitespace-pre-wrap">{sqlText}</pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="glass rounded-2xl p-14 text-center text-slate-500 text-xs italic flex flex-col gap-2 items-center justify-center border border-white/5 bg-white/[0.01]">
              <div className="text-3xl mb-1">💡</div>
              <p className="font-semibold text-slate-400 text-xs">No Proactive Insights Located</p>
              <p className="text-[10px] text-slate-600 max-w-xs leading-normal">
                No insights fit this filter criteria. Try clicking the "🔄 Profile Dataset" button above to force refresh the workspace profiling engines.
              </p>
            </div>
          )}
        </div>
      )}

      {/* 4. Chart List Grid */}
      <div className="space-y-4 pt-2">
        <div className="border-b border-white/5 pb-2">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            📈 Generated Visualization Blocks
          </h3>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {charts.map((msg, idx) => (
            <div key={msg.id || idx} className="glass p-4 rounded-2xl border border-white/5 flex flex-col gap-3">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-semibold text-slate-200 font-mono">Generated Chart {idx + 1}</span>
                <span className="text-[9px] text-slate-500 font-mono">{new Date(msg.ts).toLocaleTimeString()}</span>
              </div>
              <div className="w-full bg-[#050811] rounded-xl border border-white/5 overflow-hidden">
                <ChartRenderer spec={msg.chart_data} />
              </div>
              {msg.content && (
                <div className="text-[11px] text-slate-400 bg-white/[0.01] p-3 rounded-lg border border-white/5 leading-relaxed">
                  <strong>Insight Summary:</strong> {msg.content.replace(/^.*?analysis:\s*/i, '').slice(0, 180)}...
                </div>
              )}
            </div>
          ))}
          {charts.length === 0 && (
            <div className="lg:col-span-2 glass-sm rounded-2xl p-16 text-center text-slate-500 text-xs italic flex flex-col gap-2 items-center justify-center border border-white/5 bg-[#030712]">
              <div className="text-4xl mb-2">📈</div>
              <p className="font-semibold text-slate-400 text-xs">No Visual Charts Constructed</p>
              <p className="text-[10px] text-slate-600 max-w-xs leading-normal">
                Ask the chat assistant to "plot a chart of column revenue" or use chart shortcuts to generate visual blocks.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Long-form Executive Report View Sub-Component ────────────────────────
// ── Color Theme Presets for Corporate Reports ────────────────────────────
const PRESETS = [
  { name: 'Royal Indigo', primary: '#6366f1', secondary: '#a855f7', bg: 'from-indigo-500 to-purple-600', ring: 'ring-indigo-500' },
  { name: 'Emerald Mint', primary: '#10b981', secondary: '#34d399', bg: 'from-emerald-500 to-teal-500', ring: 'ring-emerald-500' },
  { name: 'Amber Glow', primary: '#f59e0b', secondary: '#fb923c', bg: 'from-amber-500 to-orange-500', ring: 'ring-amber-500' },
  { name: 'Rose Petal', primary: '#f43f5e', secondary: '#fb7185', bg: 'from-rose-500 to-pink-500', ring: 'ring-rose-500' },
  { name: 'Slate Steel', primary: '#64748b', secondary: '#94a3b8', bg: 'from-slate-500 to-slate-400', ring: 'ring-slate-500' }
]

const getBackendUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  const browserWindow = typeof window !== 'undefined' ? window : null
  const API_HOST = browserWindow?.location?.hostname || '127.0.0.1'
  const API_PORT = browserWindow?.__DATAPILOT_API_PORT__ || '8001'
  return `http://${API_HOST}:${API_PORT}${path}`
}

// ── Long-form Executive Report View Sub-Component ────────────────────────
function ReportView() {
  const { files, activeFileId, generateBespokeReport, exportBespokeReport } = useDataPilot()
  const activeFile = files.find(f => f.file_id === activeFileId) || files[0] || null
  const columns = activeFile?.columns || []

  // Control state
  const [reportType, setReportType] = useState('executive')
  const [title, setTitle] = useState('Executive Data & Analysis Review')
  const [dateRange, setDateRange] = useState('Q1 2026')
  const [theme, setTheme] = useState(PRESETS[0])
  const [xCol, setXCol] = useState('')
  const [yCol, setYCol] = useState('')
  const [chartType, setChartType] = useState('bar')
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(null)
  const [reportData, setReportData] = useState(null)

  // Sync controls with active file
  useEffect(() => {
    if (activeFile) {
      const cols = activeFile.columns || []
      const defaultX = cols[0]?.name || ''
      const numCols = cols.filter(c => 
        c.dtype?.includes('int') || 
        c.dtype?.includes('float') || 
        c.dtype?.includes('double') || 
        c.dtype?.includes('num') || 
        c.semantic_type === 'quantity' || 
        c.semantic_type === 'revenue' || 
        c.semantic_type === 'price'
      )
      const defaultY = numCols[0]?.name || cols[1]?.name || cols[0]?.name || ''
      setXCol(defaultX)
      setYCol(defaultY)
      setReportData(null) // trigger clean generation state
    }
  }, [activeFile?.file_id])

  // Auto-generation on load
  useEffect(() => {
    if (activeFile && !reportData && !generating && xCol && yCol) {
      handleGenerate()
    }
  }, [activeFile?.file_id, xCol, yCol])

  const handleGenerate = async () => {
    if (!activeFile) return
    setGenerating(true)
    try {
      const options = {
        file_id: activeFile.file_id,
        report_type: reportType,
        title: title || 'Executive Data Report',
        date_range: dateRange || 'All Periods',
        brand_colors: { primary: theme.primary, secondary: theme.secondary },
        x_col: xCol,
        y_col: yCol,
        chart_type: chartType
      }
      const data = await generateBespokeReport(options)
      if (data && data.success) {
        setReportData(data)
      } else {
        console.error('Narrative generation returned unsuccessful')
      }
    } catch (err) {
      console.error('Failed to compile report: ', err)
    } finally {
      setGenerating(false)
    }
  }

  const handleExport = async (format) => {
    if (!activeFile) return
    setExporting(format)
    try {
      const options = {
        file_id: activeFile.file_id,
        format: format,
        title: reportData?.title || title || 'Executive Data Report',
        date_range: reportData?.date_range || dateRange || 'All Periods',
        narrative: reportData?.narrative || '',
        kpis: reportData?.kpis || [],
        chart_type: chartType,
        x_col: xCol,
        y_col: yCol,
        brand_colors: { primary: theme.primary, secondary: theme.secondary }
      }
      await exportBespokeReport(options)
    } catch (err) {
      console.error('Failed to export document: ', err)
    } finally {
      setExporting(null)
    }
  }

  if (files.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center gap-4 bg-[#030712] text-slate-500 p-8">
        <div className="text-5xl select-none">📖</div>
        <h3 className="text-sm font-semibold text-slate-300">Branded Executive Report Builder</h3>
        <p className="text-xs text-slate-500 max-w-sm leading-relaxed">
          Unlock publication-grade, professionally branded business reports compiled into PDF, Word DOCX, PowerPoint PPTX, or Excel XLSX formats.
        </p>
        <div className="mt-2 text-[10px] text-slate-600 border border-white/5 bg-white/[0.02] px-3.5 py-2.5 rounded-xl max-w-xs leading-normal">
          ⚡ <strong>First step:</strong> Go to the sidebar or chat view and upload a spreadsheet dataset (CSV/XLSX) to populate the builder canvas.
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-hidden p-6 bg-[#030712] animate-fade-in">
      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-6 overflow-hidden h-full">
        {/* Left Designer Panel */}
        <div className="bg-[#0b0f19] border border-white/5 rounded-2xl p-5 space-y-4 overflow-y-auto max-h-full custom-scrollbar">
          <div>
            <h2 className="text-xs font-bold text-slate-200 uppercase tracking-widest">Branding Designer</h2>
            <p className="text-[10px] text-slate-500 mt-0.5">Configure report templates and brand aesthetics</p>
          </div>

          {files.length > 1 && (
            <div className="space-y-1">
              <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider block">Active Dataset</label>
              <select
                value={activeFileId || activeFile.file_id}
                onChange={(e) => useDataPilot.getState().setActiveFileId(e.target.value)}
                className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer font-semibold"
              >
                {files.map(f => (
                  <option key={f.file_id} value={f.file_id} className="bg-[#0b0f19] text-slate-200">{f.filename}</option>
                ))}
              </select>
            </div>
          )}

          <hr className="border-white/5" />

          {/* Template Selection */}
          <div className="space-y-1">
            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Report Template</label>
            <div className="grid grid-cols-3 gap-1 bg-[#050811] p-1 rounded-xl border border-white/5">
              {['executive', 'operational', 'forecast'].map((type) => (
                <button
                  key={type}
                  onClick={() => setReportType(type)}
                  className={`py-1 px-1 rounded-lg text-[9px] font-semibold uppercase tracking-wider transition-all border-0 cursor-pointer ${
                    reportType === type
                      ? 'bg-brand-600 text-white shadow-md shadow-brand-600/20 font-bold'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 bg-transparent'
                  }`}
                >
                  {type.slice(0, 4)}
                </button>
              ))}
            </div>
          </div>

          {/* Document Title */}
          <div className="space-y-1">
            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Document Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-[#050811] border border-white/5 rounded-xl px-3 py-2 text-xs font-medium text-slate-200 focus:outline-none focus:border-brand-500/35"
              placeholder="Report Title"
            />
          </div>

          {/* Date Period */}
          <div className="space-y-1">
            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Date Period</label>
            <input
              type="text"
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="w-full bg-[#050811] border border-white/5 rounded-xl px-3 py-2 text-xs font-medium text-slate-200 focus:outline-none focus:border-brand-500/35"
              placeholder="e.g. Q1 2026"
            />
          </div>

          {/* Corporate Palette */}
          <div className="space-y-1.5">
            <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider block">Corporate Palette</label>
            <div className="grid grid-cols-5 gap-1.5">
              {PRESETS.map((preset) => {
                const active = theme.name === preset.name
                return (
                  <button
                    key={preset.name}
                    onClick={() => setTheme(preset)}
                    title={preset.name}
                    className={`relative h-6 rounded-lg bg-gradient-to-br ${preset.bg} border-0 focus:outline-none cursor-pointer transition-all ${
                      active ? 'ring-2 ring-offset-2 ring-offset-[#0b0f19] ' + preset.ring : 'hover:opacity-90'
                    }`}
                  />
                )
              })}
            </div>
            <span className="text-[8px] text-slate-500 block italic">Theme: {theme.name}</span>
          </div>

          <hr className="border-white/5" />

          {/* Visualization Config */}
          <div className="space-y-3">
            <div>
              <h3 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Dynamic Visual Config</h3>
              <p className="text-[8px] text-slate-500">Pick columns mapped into Matplotlib OOP figures</p>
            </div>
            
            {/* Chart Type */}
            <div className="space-y-1">
              <label className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">Visual Type</label>
              <select
                value={chartType}
                onChange={(e) => setChartType(e.target.value)}
                className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer"
              >
                <option value="bar">📊 Bar Chart Breakdown</option>
                <option value="line">📈 Line Trend Plot</option>
                <option value="scatter">░ Scatter Correlation</option>
              </select>
            </div>

            {/* X Axis */}
            <div className="space-y-1">
              <label className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">X Dimension (Labels)</label>
              <select
                value={xCol}
                onChange={(e) => setXCol(e.target.value)}
                className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer"
              >
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.label || c.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Y Axis */}
            <div className="space-y-1">
              <label className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">Y Metric (Numbers)</label>
              <select
                value={yCol}
                onChange={(e) => setYCol(e.target.value)}
                className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer"
              >
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.label || c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <hr className="border-white/5" />

          {/* Generate Button */}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full bg-gradient-to-r from-brand-600 to-violet-600 hover:from-brand-500 hover:to-violet-500 text-white font-bold py-2 px-3 rounded-xl text-xs flex items-center justify-center gap-2 border-0 cursor-pointer shadow-lg shadow-brand-600/10 disabled:opacity-50 transition-all"
          >
            {generating ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                <span>Compiling Draft...</span>
              </>
            ) : (
              <>
                <span>🔄 Compile Branded Report</span>
              </>
            )}
          </button>
        </div>

        {/* Right Preview Workspace */}
        <div className="bg-[#070b14] border border-white/5 rounded-2xl flex flex-col overflow-hidden relative min-h-0 h-full">
          
          {/* Top Control Bar */}
          <div className="flex-shrink-0 bg-[#0b0f19]/80 backdrop-blur-md px-5 py-3 border-b border-white/5 flex items-center justify-between z-20">
            <div className="flex items-center gap-2">
              <span className="text-slate-300 font-bold text-xs">Print A4 Canvas Preview</span>
              {generating && (
                <span className="bg-brand-500/10 text-brand-400 px-1.5 py-0.5 rounded text-[8px] font-mono font-semibold animate-pulse">
                  SYNCING WITH BACKEND
                </span>
              )}
            </div>
            
            {/* Export Dock */}
            <div className="flex items-center gap-1">
              {[
                { format: 'pdf', label: 'PDF', color: 'bg-rose-600 hover:bg-rose-500' },
                { format: 'docx', label: 'Word', color: 'bg-blue-600 hover:bg-blue-500' },
                { format: 'pptx', label: 'PowerPoint', color: 'bg-orange-600 hover:bg-orange-500' },
                { format: 'xlsx', label: 'Excel', color: 'bg-emerald-600 hover:bg-emerald-500' },
              ].map((btn) => {
                const isExp = exporting === btn.format
                return (
                  <button
                    key={btn.format}
                    onClick={() => handleExport(btn.format)}
                    disabled={generating || exporting !== null}
                    className={`py-1 px-2.5 rounded-lg text-[9px] font-bold text-white transition-all border-0 cursor-pointer flex items-center gap-1 disabled:opacity-30 ${btn.color}`}
                  >
                    {isExp ? (
                      <svg className="animate-spin h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                    ) : (
                      <span>📥</span>
                    )}
                    <span>{btn.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Physical Document Scroll viewport */}
          <div className="flex-1 overflow-y-auto p-8 flex justify-center custom-scrollbar bg-slate-950/40 relative">
            {generating && !reportData ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center gap-3 bg-[#070b14]/80 backdrop-blur-sm z-10">
                <svg className="animate-spin h-8 w-8 text-brand-500" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                <div className="space-y-1">
                  <h3 className="text-xs font-semibold text-slate-300">Assembling Analytics & Insights</h3>
                  <p className="text-[10px] text-slate-500 max-w-xs leading-normal">
                    Matplotlib is generating themed vector graphics while the ReportAgent compiles business narrative sections...
                  </p>
                </div>
              </div>
            ) : null}

            {reportData ? (
              /* A4 Physical Layout Canvas */
              <div className="max-w-[210mm] w-full min-h-[297mm] bg-white text-slate-800 shadow-2xl p-12 border border-slate-200 rounded-sm flex flex-col justify-between font-sans leading-relaxed select-all">
                <div className="space-y-5">
                  
                  {/* Header & Logo Accent */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-center border-b pb-2.5" style={{ borderColor: theme.primary + '1a' }}>
                      <div className="flex items-center gap-2">
                        <svg className="w-5 h-5 animate-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path d="M12 2L2 7L12 12L22 7L12 2Z" fill={theme.primary} />
                          <path d="M2 17L12 22L22 17" stroke={theme.secondary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          <path d="M2 12L12 17L22 12" stroke={theme.primary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <span className="font-bold tracking-tight text-slate-800 text-[10px] uppercase font-mono">
                          DataPilot <span style={{ color: theme.primary }}>Analytics OS</span>
                        </span>
                      </div>
                      <div className="text-[8px] font-mono tracking-wider font-semibold text-slate-400 uppercase">
                        CONFIDENTIAL · {reportType.toUpperCase()} REPORT
                      </div>
                    </div>
                    {/* Color bar */}
                    <div className="h-[3px] w-full bg-gradient-to-r" style={{ backgroundImage: `linear-gradient(to right, ${theme.primary}, ${theme.secondary})` }} />
                  </div>

                  {/* Metadata Header */}
                  <div className="space-y-1">
                    <h1 className="text-lg font-extrabold text-slate-900 tracking-tight" style={{ color: theme.primary }}>
                      {reportData.title || title}
                    </h1>
                    <div className="flex flex-wrap items-center gap-2 text-[9px] text-slate-400 font-medium">
                      <span><strong>Date Range:</strong> {reportData.date_range || 'All Periods'}</span>
                      <span>·</span>
                      <span><strong>Author:</strong> DataPilot LLM ReportEngine</span>
                      <span>·</span>
                      <span><strong>Format:</strong> High-Resolution Print Ready</span>
                    </div>
                  </div>

                  {/* Section 1: Overview & Narrative */}
                  <div className="space-y-2">
                    <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                      1. Executive Overview & Narrative Details
                    </div>
                    <div className="prose prose-sm text-slate-700 max-w-none text-[11px] leading-relaxed font-sans space-y-3">
                      <ReactMarkdown
                        components={{
                          h1: ({node, ...props}) => <h1 className="text-[11px] font-bold text-slate-800 border-b pb-1 mt-3" style={{ borderColor: theme.primary + '1a', color: theme.primary }} {...props} />,
                          h2: ({node, ...props}) => <h2 className="text-[10px] font-bold text-slate-800 mt-2" style={{ color: theme.primary }} {...props} />,
                          h3: ({node, ...props}) => <h3 className="text-[9.5px] font-semibold text-slate-700 mt-1.5" {...props} />,
                          p: ({node, ...props}) => <p className="mb-1.5 text-[10px] leading-normal" {...props} />,
                          ul: ({node, ...props}) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5" {...props} />,
                          ol: ({node, ...props}) => <ol className="list-decimal pl-4 mb-1.5 space-y-0.5" {...props} />,
                          li: ({node, ...props}) => <li className="text-[9.5px]" {...props} />,
                          strong: ({node, ...props}) => <strong className="font-bold text-slate-900" {...props} />,
                          code: ({node, ...props}) => <code className="bg-slate-50 px-1 py-0.5 rounded text-[8.5px] font-mono text-slate-600" {...props} />,
                        }}
                      >
                        {reportData.narrative || ''}
                      </ReactMarkdown>
                    </div>
                  </div>

                  {/* Section 2: Visualization */}
                  {reportData.chart_url && (
                    <div className="space-y-1.5">
                      <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                        2. Branded Data Performance Visualization
                      </div>
                      <div className="p-2 border border-slate-100 rounded-xl bg-slate-50/50 flex flex-col items-center shadow-sm">
                        <img
                          src={getBackendUrl(reportData.chart_url)}
                          alt="DataPilot Core Chart"
                          className="max-h-[180px] object-contain rounded-lg shadow-sm"
                        />
                        <div className="text-[7.5px] text-slate-400 font-mono mt-1.5 uppercase tracking-wider text-center">
                          Figure 1.0 — {yCol} mapped across {xCol} (Themed under corporate {theme.name} palette)
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Section 3: KPIs */}
                  {reportData.kpis && reportData.kpis.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                        3. Tabulated Performance Indicators
                      </div>
                      <div className="overflow-hidden rounded-xl border border-slate-150 shadow-sm bg-white">
                        <table className="w-full text-left text-[9.5px] border-collapse">
                          <thead>
                            <tr className="text-white text-[8.5px] font-bold font-mono uppercase tracking-wider" style={{ backgroundColor: theme.primary }}>
                              <th className="px-3.5 py-2">KPI Metric Name</th>
                              <th className="px-3.5 py-2">Calculated Value</th>
                              <th className="px-3.5 py-2 text-right">Severity Rating</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {reportData.kpis.map((kpi, idx) => (
                              <tr key={idx} className="hover:bg-slate-50/50">
                                <td className="px-3.5 py-1.5 font-medium text-slate-800">{kpi.title}</td>
                                <td className="px-3.5 py-1.5 font-mono text-slate-700">{kpi.metric}</td>
                                <td className="px-3.5 py-1.5 text-right">
                                  <span className={`px-1.5 py-0.5 rounded font-bold font-mono text-[7.5px] uppercase tracking-wider ${
                                    kpi.severity === 'error' ? 'bg-rose-50 text-rose-600' :
                                    kpi.severity === 'warning' ? 'bg-amber-50 text-amber-600' :
                                    kpi.severity === 'success' ? 'bg-emerald-50 text-emerald-600' :
                                    'bg-indigo-50 text-indigo-600'
                                  }`}>
                                    {kpi.severity || 'info'}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                </div>

                {/* Document Footer */}
                <div className="border-t border-slate-100 pt-2.5 mt-6 flex justify-between items-center text-[7.5px] text-slate-400 font-medium font-mono uppercase tracking-wider">
                  <span>CONFIDENTIAL — CORPORATE BUSINESS PERFORMANCE REPORT</span>
                  <span>Page 1 of 1</span>
                </div>
              </div>
            ) : (
              /* Staging draft placeholder card */
              <div className="max-w-[210mm] w-full min-h-[297mm] bg-white text-slate-800 shadow-2xl p-12 border border-slate-200 rounded-sm flex flex-col justify-between items-center text-center font-sans">
                <div className="my-auto space-y-4 max-w-sm">
                  <div className="text-4xl text-brand-500 animate-bounce">📊</div>
                  <h2 className="text-sm font-bold text-slate-800">Draft Document Ready for Compile</h2>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    A corporate draft is configured for the dataset <strong className="text-slate-700 font-mono">&ldquo;{activeFile.filename}&rdquo;</strong>.
                  </p>
                  <button
                    onClick={handleGenerate}
                    disabled={generating}
                    className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white font-bold py-2.5 px-4.5 rounded-xl text-xs transition-colors border-0 cursor-pointer shadow-md"
                  >
                    Compile Canvas Draft
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}

// ── Presentation View Sub-Component ───────────────────────────────────────
function PresentationView() {
  const { messages } = useDataPilot()
  const charts = messages.filter(m => m.chart_data)
  const [slide, setSlide] = useState(0)

  if (charts.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center gap-4 bg-[#030712] text-slate-500 p-8">
        <div className="text-4xl">📺</div>
        <h3 className="text-sm font-semibold text-slate-300">Distraction-free Presentation mode</h3>
        <p className="text-xs text-slate-600 max-w-xs">
          Generate charts inside the chat interface first to view them in slideshow format.
        </p>
      </div>
    )
  }

  const currentChart = charts[slide]

  return (
    <div className="h-full flex flex-col items-center justify-center p-6 bg-[#030712] animate-fade-in select-none">
      <div className="w-full max-w-4xl glass p-6 rounded-3xl border border-white/5 flex flex-col gap-4 relative">
        {/* Slides indicator */}
        <div className="absolute right-6 top-6 text-[10px] text-slate-600 font-mono">
          Slide {slide + 1} of {charts.length}
        </div>

        {/* Title */}
        <div className="px-2">
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Presenting Query Output</h2>
          <h3 className="text-sm font-bold text-slate-200 mt-1">
            {currentChart.content ? currentChart.content.replace(/^.*?analysis:\s*/i, '').slice(0, 80) : 'Visual Result'}
          </h3>
        </div>

        {/* Main Render Screen */}
        <div className="bg-[#050811] rounded-2xl border border-white/5 overflow-hidden p-2 flex items-center justify-center">
          <ChartRenderer spec={currentChart.chart_data} />
        </div>

        {/* Carousel controls */}
        <div className="flex items-center justify-between border-t border-white/5 pt-4">
          <button
            onClick={() => setSlide(s => Math.max(0, s - 1))}
            disabled={slide === 0}
            className="btn-ghost disabled:opacity-20"
          >
            ◀ Previous Slide
          </button>
          
          {/* Progress dots */}
          <div className="flex gap-1">
            {charts.map((_, i) => (
              <div
                key={i}
                onClick={() => setSlide(i)}
                className={`w-1.5 h-1.5 rounded-full cursor-pointer transition-all ${
                  slide === i ? 'bg-brand-500 w-3' : 'bg-slate-700'
                }`}
              />
            ))}
          </div>

          <button
            onClick={() => setSlide(s => Math.min(charts.length - 1, s + 1))}
            disabled={slide === charts.length - 1}
            className="btn-ghost disabled:opacity-20"
          >
            Next Slide ▶
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Workflow Templates Catalog View Sub-Component ────────────────────────
function TemplateView() {
  const {
    files,
    templates,
    templatesLoading,
    loadTemplates,
    duplicateTemplate,
    deleteTemplate,
    runTemplateOnDataset,
    loadPreviewFile
  } = useDataPilot()

  const activeFile = files[0] || null

  const [activeCategory, setActiveCategory] = useState('Sales')
  const [selectedTemplateId, setSelectedTemplateId] = useState(null)
  
  // Custom templates register state
  const [newTemplateName, setNewTemplateName] = useState('')
  const [newTemplateDesc, setNewTemplateDesc] = useState('')
  const [newTemplateCat, setNewTemplateCat] = useState('Sales')
  
  // Mapping overrides & override modal state
  const [showOverrideModal, setShowOverrideModal] = useState(false)
  const [unmappedCols, setUnmappedCols] = useState([])
  const [availableCols, setAvailableCols] = useState([])
  const [mappingOverrides, setMappingOverrides] = useState({})
  
  // Execution loading states
  const [running, setRunning] = useState(false)
  const [asyncTask, setAsyncTask] = useState(null)
  const [successMsg, setSuccessMsg] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)

  // Initial load
  useEffect(() => {
    loadTemplates()
  }, [])

  // Auto-select first template in the list when category changes
  const categoryTemplates = templates.filter(t => {
    if (activeCategory === 'Custom') {
      return !t.is_builtin
    }
    return t.category?.toLowerCase() === activeCategory.toLowerCase() && t.is_builtin
  })

  useEffect(() => {
    if (categoryTemplates.length > 0) {
      setSelectedTemplateId(categoryTemplates[0].template_id)
    } else {
      setSelectedTemplateId(null)
    }
  }, [activeCategory, templates])

  // Polling for async background tasks
  useEffect(() => {
    if (!asyncTask || !activeFile) return

    const interval = setInterval(async () => {
      await loadPreviewFile(activeFile.file_id)
      const refreshed = useDataPilot.getState().files.find(f => f.file_id === activeFile.file_id)
      const task = refreshed?.metadata?.async_task

      if (task) {
        if (task.status === 'completed') {
          setAsyncTask(null)
          clearInterval(interval)
          setSuccessMsg('Background workflow template applied successfully!')
          setTimeout(() => setSuccessMsg(null), 5000)
        } else if (task.status === 'failed') {
          setAsyncTask(null)
          clearInterval(interval)
          setErrorMsg(`Background pipeline execution failed: ${task.error}`)
          setTimeout(() => setErrorMsg(null), 6000)
        } else {
          setAsyncTask(task)
        }
      } else {
        setAsyncTask(null)
        clearInterval(interval)
      }
    }, 1500)

    return () => clearInterval(interval)
  }, [asyncTask, activeFile?.file_id])

  const selectedTemplate = templates.find(t => t.template_id === selectedTemplateId) || null

  const handleRun = async (templateId, overrides = null) => {
    if (!activeFile) {
      setErrorMsg('No active spreadsheet file loaded to execute template workflows.')
      setTimeout(() => setErrorMsg(null), 4000)
      return
    }

    setRunning(true)
    setSuccessMsg(null)
    setErrorMsg(null)

    try {
      const res = await runTemplateOnDataset(activeFile.file_id, templateId, overrides)
      if (res && res.error_type === 'column_mapping_required') {
        // Halt & trigger mapping overrides editor modal
        setUnmappedCols(res.unmapped_columns || [])
        setAvailableCols(res.available_columns || [])
        const initial = {}
        ;(res.unmapped_columns || []).forEach(c => {
          initial[c.template_col] = ''
        })
        setMappingOverrides(initial)
        setShowOverrideModal(true)
      } else if (res && res.status === 'processing') {
        setAsyncTask(res)
      } else if (res && res.success) {
        setSuccessMsg('Corporate workflow template applied successfully!')
        setTimeout(() => setSuccessMsg(null), 4000)
      } else {
        setErrorMsg(res.error || 'Failed to apply template.')
        setTimeout(() => setErrorMsg(null), 4000)
      }
    } catch (err) {
      setErrorMsg(err.message)
      setTimeout(() => setErrorMsg(null), 4000)
    } finally {
      setRunning(false)
    }
  }

  const handleRunOverrides = async () => {
    setShowOverrideModal(false)
    // Check if any mapping is still unselected
    const empty = Object.values(mappingOverrides).some(val => val === '')
    if (empty) {
      setErrorMsg('All low-confidence template columns must be manually mapped.')
      setTimeout(() => setErrorMsg(null), 4000)
      return
    }
    await handleRun(selectedTemplateId, mappingOverrides)
  }

  const handleDuplicate = async (e, tId) => {
    e.stopPropagation()
    const res = await duplicateTemplate(tId)
    if (res && res.success) {
      setSuccessMsg(`Duplicated template into custom workspace: ${res.template.name}`)
      setActiveCategory('Custom')
      setSelectedTemplateId(res.template.template_id)
      setTimeout(() => setSuccessMsg(null), 4000)
    }
  }

  const handleDelete = async (e, tId) => {
    e.stopPropagation()
    if (confirm('Delete this custom template permanently?')) {
      const res = await deleteTemplate(tId)
      if (res && res.success) {
        setSuccessMsg('Template deleted successfully.')
        setTimeout(() => setSuccessMsg(null), 3000)
      }
    }
  }

  const handleSaveTemplate = async () => {
    if (!activeFile) return
    const options = {
      name: newTemplateName,
      description: newTemplateDesc || 'Saved pipeline workflow',
      category: newTemplateCat,
      file_id: activeFile.file_id
    }
    const res = await useDataPilot.getState().saveCustomTemplate(options)
    if (res && res.success) {
      setSuccessMsg(`Workflow saved as custom template: ${res.template.name}`)
      setNewTemplateName('')
      setNewTemplateDesc('')
      setActiveCategory('Custom')
      setSelectedTemplateId(res.template.template_id)
      setTimeout(() => setSuccessMsg(null), 4000)
    } else {
      setErrorMsg(res.error || 'Failed to save workflow. Ensure transformations are applied first.')
      setTimeout(() => setErrorMsg(null), 4000)
    }
  }

  return (
    <div className="h-full overflow-hidden p-6 bg-[#030712] animate-fade-in flex flex-col gap-4">
      
      {/* Toast notifications */}
      {successMsg && (
        <div className="fixed bottom-6 right-6 bg-emerald-500/10 border border-emerald-500/25 px-4 py-3 rounded-xl text-emerald-300 text-xs font-semibold shadow-xl z-50 flex items-center gap-2 animate-slide-in">
          <span>✅</span> {successMsg}
        </div>
      )}
      {errorMsg && (
        <div className="fixed bottom-6 right-6 bg-rose-500/10 border border-rose-500/25 px-4 py-3 rounded-xl text-rose-300 text-xs font-semibold shadow-xl z-50 flex items-center gap-2 animate-slide-in">
          <span>⚠️</span> {errorMsg}
        </div>
      )}

      {/* Main split dashboard templates grid */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6 overflow-hidden h-full">
        
        {/* Left column catalog */}
        <div className="flex flex-col min-h-0 h-full gap-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-200">🗂️ Workflow Templates Catalog</h2>
              <p className="text-[10px] text-slate-500 mt-0.5">Deploy repeatable, highly structured business processing scripts</p>
            </div>
            
            {/* Functional Category tabs selector */}
            <div className="flex p-1 bg-[#0d1222] rounded-xl border border-white/5">
              {['Sales', 'Finance', 'Inventory', 'HR', 'Custom'].map(cat => (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`py-1 px-3.5 rounded-lg text-[10px] font-bold transition-all border-0 cursor-pointer ${
                    activeCategory === cat
                      ? 'bg-brand-600 text-white font-extrabold shadow-md shadow-brand-600/15'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 bg-transparent'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Cards Grid */}
          <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar min-h-0">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {categoryTemplates.map(t => {
                const isSelected = selectedTemplateId === t.template_id
                return (
                  <div
                    key={t.template_id}
                    onClick={() => setSelectedTemplateId(t.template_id)}
                    className={`p-4.5 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between gap-4 relative group ${
                      isSelected
                        ? 'bg-brand-500/10 border-brand-500/30'
                        : 'bg-[#0d1222]/40 hover:bg-[#0d1222]/80 border-white/5'
                    }`}
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[9px] font-bold text-brand-400 uppercase tracking-widest font-mono bg-brand-500/5 px-2 py-0.5 rounded-md">
                          {t.category}
                        </span>
                        
                        <div className="flex items-center gap-1 opacity-65 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => handleDuplicate(e, t.template_id)}
                            title="Duplicate Workflow Template"
                            className="p-1 bg-white/5 hover:bg-white/10 rounded border-0 text-[10px] cursor-pointer text-slate-300 transition-all"
                          >
                            👥 Duplicate
                          </button>
                          {!t.is_builtin && (
                            <button
                              onClick={(e) => handleDelete(e, t.template_id)}
                              title="Delete Custom Template"
                              className="p-1 bg-rose-500/10 hover:bg-rose-500/20 rounded border-0 text-[10px] cursor-pointer text-rose-400 transition-all font-mono"
                            >
                              🗑️ Delete
                            </button>
                          )}
                        </div>
                      </div>
                      
                      <h3 className="text-xs font-bold text-slate-200">{t.name}</h3>
                      <p className="text-[10px] text-slate-500 leading-normal">{t.description}</p>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-white/5">
                      <span className="text-[9px] font-mono text-slate-500 uppercase font-semibold">
                        {t.steps?.length || 0} Steps
                      </span>
                      <span className="text-[9.5px] font-bold text-brand-400 group-hover:translate-x-1 transition-transform">
                        Configure pipeline →
                      </span>
                    </div>
                  </div>
                )
              })}

              {categoryTemplates.length === 0 && (
                <div className="col-span-full py-16 text-center text-slate-600 text-xs italic flex flex-col gap-2 items-center justify-center bg-[#0d1222]/10 rounded-2xl border border-white/5">
                  <div className="text-3xl">🗂️</div>
                  <p className="font-semibold text-slate-400">No Reusable Templates Saved</p>
                  <p className="text-[9px] text-slate-600 max-w-xs leading-normal">
                    {activeCategory === 'Custom'
                      ? 'Apply a sequence of transformations to a file, then type a name in the Register panel on the right to save a reusable template.'
                      : 'No default templates are registered for this category.'}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right column Selected pipeline preview */}
        <div className="flex flex-col min-h-0 h-full gap-4">
          <div className="bg-[#0b0f19] border border-white/5 rounded-2xl p-5 flex flex-col min-h-0 h-full gap-4 justify-between">
            <div className="space-y-4 flex-1 overflow-y-auto pr-1 custom-scrollbar min-h-0">
              
              {/* Selected template info header */}
              {selectedTemplate ? (
                <div className="space-y-3">
                  <div>
                    <span className="text-[8px] font-bold text-brand-400 uppercase tracking-widest font-mono">
                      {selectedTemplate.category} Pipeline Flow
                    </span>
                    <h3 className="text-xs font-bold text-slate-200 mt-0.5">{selectedTemplate.name}</h3>
                    <p className="text-[10px] text-slate-500 leading-normal mt-1">{selectedTemplate.description}</p>
                  </div>

                  <hr className="border-white/5" />

                  {/* Flow chart stepflow mapping catalog */}
                  <div className="space-y-2">
                    <h4 className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                      Visual Pipeline Mapping Checks
                    </h4>
                    
                    <div className="space-y-2">
                      {selectedTemplate.steps.map((step, idx) => {
                        const targetCol = step.column || step.target || (step.columns ? step.columns.join(', ') : '')
                        
                        let statusText = 'Exact Match'
                        let statusColor = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                        let confidenceVal = 100

                        if (activeFile) {
                          const dfCols = activeFile.columns || []
                          const semanticMap = activeFile.metadata?.semantic_map || {}
                          
                          const hasExact = dfCols.some(c => c.name === targetCol)
                          if (!hasExact) {
                            const hasCase = dfCols.some(c => c.name.toLowerCase() === targetCol.lower())
                            if (hasCase) {
                              statusText = 'Case Match'
                              statusColor = 'bg-teal-500/10 text-teal-400 border-teal-500/20'
                              confidenceVal = 99
                            } else {
                              // Check semantic mapping fallbacks
                              let bestCol = null
                              let bestConf = 0.0
                              for (const [col, meta] of Object.entries(semanticMap)) {
                                const semType = String(meta.semantic_type || '').lower()
                                const label = String(meta.label || '').lower()
                                const inferred = String(meta.inferred_meaning || '').lower()
                                const conf = parseFloat(meta.confidence || 0.6)
                                if (targetCol.toLowerCase() in (semType, label) || targetCol.toLowerCase() in inferred) {
                                  if (conf > bestConf) {
                                    bestConf = conf
                                    bestCol = col
                                  }
                                }
                              }
                              if (bestCol && bestConf >= 0.85) {
                                statusText = `AI Match: ${bestCol}`
                                statusColor = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30 font-bold glow-emerald-sm animate-pulse'
                                confidenceVal = Math.round(bestConf * 100)
                              } else {
                                statusText = 'Low Confidence / Review Required'
                                statusColor = 'bg-rose-500/10 text-rose-400 border-rose-500/20 font-semibold'
                                confidenceVal = 0
                              }
                            }
                          }
                        } else {
                          statusText = 'No Dataset'
                          statusColor = 'bg-slate-500/10 text-slate-400 border-slate-500/20'
                          confidenceVal = 0
                        }

                        return (
                          <div key={idx} className="flex items-center gap-3 bg-[#050811] p-3 rounded-xl border border-white/5">
                            <div className="w-5 h-5 rounded-full bg-brand-500/20 border border-brand-500/35 flex items-center justify-center text-[9px] font-bold font-mono text-brand-300">
                              {idx + 1}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[10px] font-bold text-slate-200 capitalize font-mono">{step.action.replace('_', ' ')}</span>
                                <span className="text-[8px] px-1 py-0.5 rounded bg-white/5 text-slate-400 font-mono">
                                  {targetCol}
                                </span>
                              </div>
                              <p className="text-[8.5px] text-slate-500 truncate mt-0.5">{step.description || 'Applies workflow transformation step'}</p>
                            </div>

                            <div className={`px-1.5 py-0.5 rounded text-[8px] font-bold font-mono border ${statusColor}`} title={statusText}>
                              {statusText.slice(0, 15)} {confidenceVal > 0 && `(${confidenceVal}%)`}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  <hr className="border-white/5" />

                  {/* Asynchronous task tracking status block */}
                  {asyncTask && (
                    <div className="bg-[#050811] border border-brand-500/20 rounded-xl p-3.5 space-y-2 animate-pulse text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-brand-300 font-bold">⚡ Running Async Gateway Pipeline</span>
                        <span className="font-mono text-[9px] text-slate-400">{asyncTask.progress}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all duration-300"
                          style={{ width: `${asyncTask.progress}%` }}
                        />
                      </div>
                      <p className="text-[9px] text-slate-500 font-medium">
                        Pipeline contains heavy file parameters (10,000+ rows). Processing safely in background worker pool...
                      </p>
                    </div>
                  )}

                  {/* Trigger execute button */}
                  {!asyncTask && (
                    <button
                      onClick={() => handleRun(selectedTemplate.template_id)}
                      disabled={running || !activeFile}
                      className="w-full bg-gradient-to-r from-brand-600 to-violet-600 hover:from-brand-500 hover:to-violet-500 text-white font-bold py-2 px-4 rounded-xl text-xs flex items-center justify-center gap-2 border-0 cursor-pointer shadow-lg shadow-brand-600/10 disabled:opacity-30 transition-all"
                    >
                      {running ? (
                        <>
                          <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                          </svg>
                          <span>Executing Workflow...</span>
                        </>
                      ) : (
                        <>
                          <span>⚡ Run Reusable Workflow</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center text-slate-600 text-[10px] italic py-20">
                  Select a workflow card to view planned steps and deploy.
                </div>
              )}

              {/* Custom template register form */}
              {activeFile && (
                <div className="pt-4 border-t border-white/5">
                  <div className="glass p-4.5 rounded-2xl border border-white/5 space-y-3">
                    <div>
                      <h3 className="text-xs font-bold text-slate-200">💾 Register Active Workflow</h3>
                      <p className="text-[9px] text-slate-500 mt-0.5">Save your applied transformations history as a reusable template</p>
                    </div>
                    
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder="Workflow Template Name"
                        value={newTemplateName}
                        onChange={(e) => setNewTemplateName(e.target.value)}
                        className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none"
                      />
                      <input
                        type="text"
                        placeholder="Description (e.g. Cleans GST Sales log)"
                        value={newTemplateDesc}
                        onChange={(e) => setNewTemplateDesc(e.target.value)}
                        className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none"
                      />
                      
                      <div className="grid grid-cols-2 gap-1.5">
                        <select
                          value={newTemplateCat}
                          onChange={(e) => setNewTemplateCat(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-xl px-2 py-1.5 text-[10px] text-slate-300 focus:outline-none cursor-pointer"
                        >
                          <option value="Sales">Sales Cat</option>
                          <option value="Finance">Finance Cat</option>
                          <option value="Inventory">Inventory Cat</option>
                          <option value="HR">HR Cat</option>
                        </select>
                        
                        <button
                          onClick={handleSaveTemplate}
                          disabled={!newTemplateName.trim()}
                          className="bg-slate-200 hover:bg-white text-slate-900 font-bold py-1 px-2.5 rounded-xl text-[10px] border-0 cursor-pointer disabled:opacity-35 transition-colors font-sans"
                        >
                          Register Workflow
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>
      </div>

      {/* Manual Column Overrides Editor Modal (The 85% Confidence Gate override triggers) */}
      {showOverrideModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="w-full max-w-sm bg-[#0b0f19] border border-white/10 rounded-2xl p-6 space-y-4 shadow-2xl animate-scale-up">
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                ⚠️ Review Column Mapping Required
              </h3>
              <p className="text-[10px] text-slate-500 leading-normal">
                Template targets properties that do not exist or have low semantic confidence in the active sheet. Please map manually:
              </p>
            </div>

            <div className="space-y-3 max-h-52 overflow-y-auto pr-1 custom-scrollbar">
              {unmappedCols.map(col => (
                <div key={col.template_col} className="space-y-1.5 p-3 rounded-xl bg-[#050811] border border-white/5">
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] font-bold text-slate-300 font-mono uppercase tracking-wider">
                      Template property: {col.template_col}
                    </span>
                    <span className="text-[8px] bg-rose-500/10 text-rose-400 px-1 rounded font-mono font-bold tracking-widest uppercase">unmapped</span>
                  </div>
                  
                  <select
                    value={mappingOverrides[col.template_col] || ''}
                    onChange={(e) => setMappingOverrides({
                      ...mappingOverrides,
                      [col.template_col]: e.target.value
                    })}
                    className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-2 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer font-mono"
                  >
                    <option value="">-- Choose matching column --</option>
                    {availableCols.map(c => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2.5 pt-2">
              <button
                onClick={() => setShowOverrideModal(false)}
                className="flex-1 bg-white/5 hover:bg-white/10 text-slate-400 font-bold py-2 rounded-xl text-xs transition-colors border-0 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleRunOverrides}
                className="flex-1 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold py-2 rounded-xl text-xs border-0 cursor-pointer shadow-lg shadow-emerald-600/15"
              >
                Commit Overrides
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}


// ── Tab button (Analyst mode tab) ─────────────────────────────────────────
function TabBtn({ id, label, active, onClick }) {
  return (
    <button
      id={id}
      onClick={onClick}
      className={`flex-1 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
        active
          ? 'bg-brand-500/10 text-brand-300 border border-brand-500/25'
          : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
      }`}
    >
      {label}
    </button>
  )
}

// ── Layout Main Redesign ──────────────────────────────────────────────────
export default function App() {
  const {
    workspaceMode,
    setWorkspaceMode,
    activeTab,
    setActiveTab,
    files,
  } = useDataPilot()

  const [paletteOpen, setPaletteOpen] = useState(false)

  // Listen for Ctrl+K / Cmd+K hotkey
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="noise flex h-screen overflow-hidden bg-[#030712]">
      {/* Ambient purple blurs */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="ambient-glow top-[-20%] left-[-15%] opacity-15"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)' }} />
        <div className="ambient-glow bottom-[-10%] right-[-10%] opacity-10"
          style={{ background: 'radial-gradient(circle, #8b5cf6 0%, transparent 70%)' }} />
        <div className="ambient-glow top-[30%] right-[30%] opacity-5"
          style={{ background: 'radial-gradient(circle, #3b82f6 0%, transparent 70%)' }} />
      </div>

      {/* ── Left Sidebar ─────────────────────────────────────────────────── */}
      <aside className="sidebar z-10">
        {/* Brand Logo */}
        <div className="px-4.5 pt-5 pb-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center text-lg shadow-lg border border-brand-500/25 bg-gradient-to-br from-brand-600 to-purple-600">
              🧭
            </div>
            <div>
              <h1 className="text-xs font-bold tracking-tight text-white leading-none">DataPilot</h1>
              <p className="text-[9px] text-slate-500 mt-1 font-mono">Local AI OS · v1.2</p>
            </div>
          </div>
        </div>

        {/* Workspace Selector dropdown */}
        <div className="px-3 pt-4 pb-2">
          <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider px-1 block mb-1.5">
            Workspace Mode
          </label>
          <select
            value={workspaceMode}
            onChange={(e) => setWorkspaceMode(e.target.value)}
            className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-2.5 py-2 text-xs font-semibold text-slate-300 focus:outline-none focus:border-brand-500/35 cursor-pointer"
          >
            <option value="chat">💬 Conversational Chat</option>
            <option value="dashboard">📊 Metric Dashboard</option>
            <option value="report">📖 Narrative Report</option>
            <option value="analyst">🧠 Advanced Spreadsheet</option>
            <option value="presentation">📺 Fullscreen Present</option>
            <option value="templates">🗂️ Workflow Templates</option>
            <option value="saved">💾 Saved Analyses</option>
            <option value="reports">📋 Saved Reports</option>
            <option value="history">📜 Query History</option>
            <option value="datasets">📦 Dataset Manager</option>
          </select>
        </div>

        {/* AI local provider status */}
        <div className="px-3 py-1.5">
          <AIStatus />
          <div className="mt-1.5">
            <ProviderSelector />
          </div>
        </div>

        {/* Dataset file uploader list */}
        <div className="flex-1 overflow-y-auto px-3 py-2 custom-scrollbar">
          <FileUploader />
          <SessionManager />
        </div>

        {/* Sidebar Footer */}
        <div className="px-4.5 py-3 border-t border-white/5 flex items-center justify-between text-[10px] text-slate-600 bg-black/10">
          <kbd className="px-1.5 py-0.5 rounded bg-white/5 border border-white/5 font-mono text-[9px] text-slate-500">
            Ctrl+K Palette
          </kbd>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="text-brand-400 hover:text-brand-300 transition-colors font-medium"
          >
            API Docs →
          </a>
        </div>
      </aside>

      {/* ── Main Workspace Area ──────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 z-10 bg-[#030712]">
        
        {/* App body renderer based on Workspace Mode state */}
        <div className="flex-1 overflow-hidden">
          {workspaceMode === 'chat' && (
            <ChatWindow />
          )}

          {workspaceMode === 'dashboard' && (
            <DashboardView />
          )}

          {workspaceMode === 'report' && (
            <ReportView />
          )}

          {workspaceMode === 'presentation' && (
            <PresentationView />
          )}

          {workspaceMode === 'templates' && (
            <TemplateView />
          )}

          {workspaceMode === 'saved' && (
            <SavedAnalyses />
          )}

          {workspaceMode === 'reports' && (
            <SavedReports />
          )}

          {workspaceMode === 'history' && (
            <QueryHistory />
          )}

          {workspaceMode === 'datasets' && (
            <DatasetManager />
          )}

          {workspaceMode === 'analyst' && (
            <div className="h-full flex flex-col">
              {/* Tab Header for Analyst Mode */}
              <div className="flex items-center gap-2 px-5 pt-3 pb-2 border-b border-white/5 flex-shrink-0 bg-[#050811]">
                <div className="flex gap-1 p-1 bg-[#0d1222] rounded-xl flex-shrink-0 border border-white/5">
                  <TabBtn
                    id="tab-preview"
                    label="🔍 Data spreadsheet"
                    active={activeTab === 'preview'}
                    onClick={() => setActiveTab('preview')}
                  />
                  <TabBtn
                    id="tab-chat-sub"
                    label="💬 Active chat prompt"
                    active={activeTab === 'chat'}
                    onClick={() => setActiveTab('chat')}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <StepIndicator />
                </div>
              </div>
              
              {/* Render spreadsheet view or chat prompt */}
              <div className="flex-1 overflow-hidden">
                {activeTab === 'preview' ? (
                  files.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center gap-4 bg-[#030712]">
                      <div className="text-4xl select-none">📂</div>
                      <h3 className="text-sm font-semibold text-slate-400">Empty Workspace</h3>
                      <p className="text-slate-600 text-xs">Upload a CSV or Excel spreadsheet to preview values here</p>
                    </div>
                  ) : (
                    <DataPreview />
                  )
                ) : (
                  <ChatWindow />
                )}
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Ctrl + K command center overlay */}
      <CommandPalette isOpen={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
