import { useEffect, useMemo, useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

const PAGE_SIZE = 50

export default function DataPreview() {
  const {
    files,
    previewFileId,
    previewLoading,
    previewError,
    previewSaving,
    exportFile,
    loadPreviewFile,
    savePreviewEdits,
    getTransformPreview,
    applyStagedTransform,
    undoLastTransform,
  } = useDataPilot()

  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(0)
  const [editMode, setEditMode] = useState(false)
  const [draftEdits, setDraftEdits] = useState({})
  const [showInsights, setShowInsights] = useState(true)
  const [selectedColumn, setSelectedColumn] = useState(null)

  // Phase 3 States
  const [showWorkflowInput, setShowWorkflowInput] = useState(false)
  const [workflowQuery, setWorkflowQuery] = useState('')
  const [transformationPlan, setTransformationPlan] = useState(null)
  const [transformLoading, setTransformLoading] = useState(false)
  const [transformError, setTransformError] = useState(null)
  const [previewTab, setPreviewTab] = useState('after') // 'before' | 'after'

  const file = files.find(f => f.file_id === previewFileId) || null

  // Helper clean function matching clean_header_to_label
  const cleanHeader = (name) => {
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  // Auto-switch rows/columns if transformation plan is active
  const activePlanColumns = useMemo(() => {
    if (!transformationPlan) return null
    const cols = previewTab === 'before' ? transformationPlan.preview_before.columns : transformationPlan.preview_after.columns
    return cols.map(c => {
      const found = file?.columns?.find(fc => fc.name === c)
      return found || { name: c, label: cleanHeader(c), dtype: 'object', semantic_type: 'text', null_count: 0, unique_count: 0 }
    })
  }, [transformationPlan, previewTab, file])

  const activePlanRows = useMemo(() => {
    if (!transformationPlan) return null
    return previewTab === 'before' ? transformationPlan.preview_before.rows : transformationPlan.preview_after.rows
  }, [transformationPlan, previewTab])

  const columns = file?.columns || []
  const visibleColumns = activePlanColumns || columns.filter(col => col.name !== '_row_index')
  const rows = activePlanRows || file?.sample_data || []

  const processed = useMemo(() => {
    let result = [...rows]
    if (filter) {
      const lower = filter.toLowerCase()
      result = result.filter(row =>
        Object.values(row).some(v => String(v ?? '').toLowerCase().includes(lower))
      )
    }
    if (sortCol) {
      result.sort((a, b) => {
        const av = a[sortCol] ?? ''
        const bv = b[sortCol] ?? ''
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    }
    return result
  }, [rows, filter, sortCol, sortDir])

  const totalPages = Math.ceil(processed.length / PAGE_SIZE)
  const pageRows = processed.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const draftCount = Object.keys(draftEdits).length

  useEffect(() => {
    if (file?.file_id && rows.length > 0 && rows.some(row => row._row_index === undefined)) {
      loadPreviewFile(file.file_id)
    }
  }, [file?.file_id, rows, loadPreviewFile])

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
    setPage(0)
  }

  const setCellDraft = (rowIndex, column, value) => {
    const key = `${rowIndex}:${column}`
    setDraftEdits(current => ({
      ...current,
      [key]: { row_index: rowIndex, column, value },
    }))
  }

  const getCellValue = (row, columnName) => {
    const key = `${row._row_index}:${columnName}`
    return draftEdits[key]?.value ?? row[columnName] ?? ''
  }

  const handleSave = async () => {
    const edits = Object.values(draftEdits)
    const result = await savePreviewEdits(file.file_id, edits)
    if (result.success) {
      setDraftEdits({})
      setEditMode(false)
    }
  }

  const handleCancel = () => {
    setDraftEdits({})
    setEditMode(false)
  }

  const handleExport = async (format) => {
    const result = await exportFile(file.file_id, format)
    if (!result?.success) {
      window.alert(result?.error || `Failed to export ${format.toUpperCase()}`)
    }
  }

  // Phase 3 Actions
  const handleProposeWorkflow = async () => {
    if (!workflowQuery.trim()) return
    setTransformLoading(true)
    setTransformError(null)
    const result = await getTransformPreview(file.file_id, workflowQuery)
    setTransformLoading(false)
    if (result.success) {
      setTransformationPlan(result)
      setPreviewTab('after')
      setPage(0)
    } else {
      setTransformError(result.error || 'Failed to generate transformation preview')
    }
  }

  const handleApplyWorkflow = async () => {
    if (!transformationPlan) return
    setTransformLoading(true)
    setTransformError(null)
    const result = await applyStagedTransform(file.file_id, transformationPlan.transformation_id)
    setTransformLoading(false)
    if (result.success) {
      setTransformationPlan(null)
      setWorkflowQuery('')
      setShowWorkflowInput(false)
      loadPreviewFile(file.file_id)
    } else {
      setTransformError(result.error || 'Failed to apply transformation')
    }
  }

  const handleDiscardWorkflow = () => {
    setTransformationPlan(null)
    setTransformError(null)
  }

  const handleUndoTransform = async () => {
    setTransformLoading(true)
    const result = await undoLastTransform(file.file_id)
    setTransformLoading(false)
    if (result.success) {
      loadPreviewFile(file.file_id)
    } else {
      window.alert(result.error || 'Failed to undo')
    }
  }

  const isCellModified = (row, columnName) => {
    if (!transformationPlan || previewTab !== 'after') return false
    const rowIndex = row._row_index
    const beforeRow = transformationPlan.preview_before.rows.find(r => r._row_index === rowIndex)
    if (!beforeRow) return false
    return String(beforeRow[columnName] ?? '') !== String(row[columnName] ?? '')
  }

  if (previewLoading || transformLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8 gap-4 bg-[#030712]">
        <div className="w-8.5 h-8.5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-400 text-xs font-mono">
          {transformLoading ? '🔮 Workflow automation processing changes...' : 'Loading data grid...'}
        </p>
      </div>
    )
  }

  if (previewError) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8 gap-4 bg-[#030712]">
        <div className="text-4xl select-none">⚠️</div>
        <p className="text-rose-400 text-xs font-mono">{previewError}</p>
      </div>
    )
  }

  if (!file) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8 gap-4 bg-[#030712]">
        <div className="text-4xl select-none">📊</div>
        <p className="text-slate-400 text-xs">Select a file from the left sidebar to preview its data spreadsheet</p>
      </div>
    )
  }

  return (
    <div className="flex h-full bg-[#030712] animate-fade-in select-none relative overflow-hidden w-full">
      {/* Spreadsheet viewport */}
      <div className="flex-1 flex flex-col h-full overflow-hidden border-r border-white/5">
        {/* Table tools header bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-white/5 flex-shrink-0 bg-[#050811]/60 backdrop-blur">
          <div>
            <h3 className="text-xs font-bold text-slate-200 flex items-center gap-2">
              📄 {file.filename}
            </h3>
            <p className="text-[10px] text-slate-500 mt-0.5 font-mono">
              {file.row_count?.toLocaleString()} rows · {file.column_count} columns
              {filter && ` · ${processed.length} match`}
            </p>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {file?.metadata?.applied_workflows?.length > 0 && (
              <button
                onClick={handleUndoTransform}
                className="btn-ghost text-[10px] h-8 bg-rose-500/10 border border-rose-500/15 hover:bg-rose-500/20 text-rose-300 font-semibold"
                title={`Undo: ${file.metadata.applied_workflows[file.metadata.applied_workflows.length - 1].description}`}
              >
                ↩️ Undo
              </button>
            )}

            <button
              onClick={() => setShowWorkflowInput(!showWorkflowInput)}
              className={`btn-ghost text-[10px] h-8 font-semibold ${
                showWorkflowInput
                  ? 'bg-brand-500/20 text-brand-300 border border-brand-500/35 shadow-[0_0_12px_-2px_rgba(99,102,241,0.2)]'
                  : 'bg-white/5 border border-white/5 hover:bg-white/10 text-slate-300'
              }`}
            >
              🧹 AI Clean / Workflow
            </button>

            {editMode ? (
              <>
                <button
                  onClick={handleSave}
                  disabled={!draftCount || previewSaving}
                  className="btn-primary h-8 px-3 disabled:opacity-40 text-[10px]"
                >
                  {previewSaving ? 'Saving...' : `Save${draftCount ? ` (${draftCount})` : ''}`}
                </button>
                <button
                  onClick={handleCancel}
                  className="btn-ghost text-[10px] h-8"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={() => setEditMode(true)}
                className="btn-ghost text-[10px] h-8 bg-white/5 border border-white/5"
              >
                ✏️ Edit Values
              </button>
            )}
            <button
              onClick={() => handleExport('csv')}
              className="btn-ghost text-[10px] h-8"
            >
              📥 CSV
            </button>
            <button
              onClick={() => handleExport('xlsx')}
              className="btn-ghost text-[10px] h-8"
            >
              📥 Excel
            </button>
            
            {/* Quick filters input box */}
            <input
              type="text"
              value={filter}
              onChange={e => { setFilter(e.target.value); setPage(0) }}
              placeholder="Quick search columns..."
              className="w-36 bg-[#080d19] border border-white/5 rounded-lg px-2.5 py-1.5 text-[10px] text-slate-300 focus:outline-none focus:border-brand-500/35"
            />
          </div>
        </div>

        {/* AI Workflow Input panel */}
        {showWorkflowInput && !transformationPlan && (
          <div className="px-5 py-3.5 border-b border-white/5 bg-[#050811]/40 backdrop-blur flex flex-col gap-2 animate-fade-in border-t border-brand-500/10">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-400 font-semibold tracking-wide flex items-center gap-1.5">
                🔮 AI Workflow Automation Planner
              </span>
              {transformError && (
                <span className="text-[9px] text-rose-400 bg-rose-500/10 border border-rose-500/10 px-2 py-0.5 rounded font-mono">
                  {transformError}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={workflowQuery}
                onChange={e => setWorkflowQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleProposeWorkflow()}
                placeholder="e.g. 'Clean this dataset', 'Filter salary > 2000', 'Group by city and mean age'"
                className="flex-1 bg-[#080d19] border border-white/10 rounded-xl px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500/40"
              />
              <button
                onClick={handleProposeWorkflow}
                disabled={!workflowQuery.trim()}
                className="btn-primary h-9 px-4 text-xs font-bold disabled:opacity-40"
              >
                Propose Changes
              </button>
            </div>
          </div>
        )}

        {/* AI Transformation Preview & Comparison Tabs */}
        {transformationPlan && (
          <div className="px-5 py-4 border-b border-white/5 bg-[#08111e]/25 backdrop-blur flex flex-col gap-3 animate-fade-in border-t border-emerald-500/20">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1">
                <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-widest block font-mono">
                  ✨ Proposed Transformation Plan
                </span>
                <p className="text-[11px] text-slate-300 leading-normal font-medium">
                  Applying changes will affect approximately <strong className="text-emerald-300 font-mono">{transformationPlan.affected_rows?.toLocaleString()} rows</strong> in the preview head slice.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex bg-[#0d1222] border border-white/5 p-1 rounded-xl">
                  <button
                    onClick={() => setPreviewTab('before')}
                    className={`px-3 py-1 rounded-lg text-[9px] font-bold uppercase tracking-wider font-mono transition-all ${
                      previewTab === 'before'
                        ? 'bg-white/5 text-slate-200 border border-white/5'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    ⏮ Before (Original)
                  </button>
                  <button
                    onClick={() => setPreviewTab('after')}
                    className={`px-3 py-1 rounded-lg text-[9px] font-bold uppercase tracking-wider font-mono transition-all ${
                      previewTab === 'after'
                        ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/25'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    ⏭ After (Dry Run)
                  </button>
                </div>

                <button
                  onClick={handleApplyWorkflow}
                  className="btn-primary h-8 px-3 text-[10px] font-bold bg-emerald-600 hover:bg-emerald-500 text-white"
                >
                  ✅ Commit & Apply
                </button>
                <button
                  onClick={handleDiscardWorkflow}
                  className="btn-ghost h-8 text-[10px] hover:bg-white/5 text-slate-400 font-bold"
                >
                  ✕ Discard Plan
                </button>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {transformationPlan.actions?.map((act, idx) => (
                <div
                  key={idx}
                  className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/5 text-[9px] text-slate-300 flex items-center gap-1.5 font-medium"
                >
                  <span className="bg-brand-500/20 text-brand-300 px-1 rounded font-mono text-[8px]">
                    {idx + 1}
                  </span>
                  <span>{act.description}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Semantic labels header list */}
        <div className="flex gap-1.5 px-5 py-2.5 overflow-x-auto border-b border-white/5 flex-shrink-0 bg-white/[0.01] custom-scrollbar">
          {visibleColumns.slice(0, 15).map(col => (
            <div
              key={col.name}
              onClick={() => setSelectedColumn(col)}
              className="flex-shrink-0 glass-sm px-2.5 py-1 rounded-lg flex items-center gap-1.5 border border-white/[0.03] text-[9px] cursor-pointer hover:border-brand-500/30 hover:text-slate-200 transition-all"
              title="Inspect column business metadata"
            >
              <span className="font-mono text-brand-300 font-semibold">{col.label || col.name}</span>
              <span className="text-slate-600 font-mono text-[8px]">({col.semantic_type || col.dtype})</span>
              {col.null_count > 0 && (
                <span className="text-amber-500/70 font-semibold">⚠️ {col.null_count} nulls</span>
              )}
            </div>
          ))}
          {visibleColumns.length > 15 && (
            <span className="flex-shrink-0 text-[10px] text-slate-600 self-center font-mono">
              +{visibleColumns.length - 15} more
            </span>
          )}
        </div>

        {/* Expandable Automated Insights deck inside Data Preview */}
        {file.metadata?.insights?.length > 0 && (
          <div className="px-5 py-2.5 border-b border-white/5 bg-brand-500/[0.01] flex-shrink-0">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                ✨ Proactive Profiling Insights
              </span>
              <button
                onClick={() => setShowInsights(prev => !prev)}
                className="text-[9px] text-slate-500 hover:text-slate-300 transition-colors"
              >
                {showInsights ? 'Hide insights ✕' : 'Show insights ＋'}
              </button>
            </div>

            {showInsights && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5 animate-fade-in select-none">
                {file.metadata.insights.slice(0, 4).map((insight, idx) => {
                  let emoji = '💡'
                  let borderClass = 'border-white/5'
                  
                  if (insight?.severity === 'error') {
                    emoji = '❌'
                    borderClass = 'border-rose-500/15 bg-rose-500/[0.01]'
                  } else if (insight?.severity === 'warning') {
                    emoji = '⚠️'
                    borderClass = 'border-amber-500/15 bg-amber-500/[0.01]'
                  } else if (insight?.severity === 'success') {
                    emoji = '✨'
                    borderClass = 'border-emerald-500/15 bg-emerald-500/[0.01]'
                  } else {
                    emoji = '✦'
                    borderClass = 'border-cyan-500/15 bg-cyan-500/[0.01]'
                  }
                  
                  const titleText = insight?.title || (typeof insight === 'string' ? insight : '')
                  
                  return (
                    <div
                      key={insight?.id || idx}
                      className={`flex gap-2 p-2 rounded-xl border text-[10px] text-slate-400 hover:border-white/10 hover:text-slate-300 hover:bg-white/[0.01] transition-all ${borderClass}`}
                    >
                      <span className="text-xs flex-shrink-0 leading-none">{emoji}</span>
                      <span className="leading-relaxed font-medium">{titleText}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Main Table spreadsheet grid view */}
        <div className="flex-1 overflow-auto custom-scrollbar">
          {pageRows.length === 0 ? (
            <div className="flex items-center justify-center h-full text-slate-600 text-xs italic">
              No rows match your filter.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th className="w-12 text-center text-slate-600 font-mono">#</th>
                  {visibleColumns.map(col => (
                    <th
                      key={col.name}
                      className="cursor-pointer select-none group/th font-mono"
                    >
                      <div className="flex items-center justify-between gap-1.5 w-full">
                        <span onClick={() => handleSort(col.name)} className="flex-1 hover:text-brand-300 truncate">{col.label || col.name}</span>
                        <span
                          onClick={(e) => { e.stopPropagation(); setSelectedColumn(col); }}
                          className="text-[9px] hover:text-brand-300 opacity-20 group-hover/th:opacity-100 transition-opacity select-none p-0.5"
                          title="Inspect column business metadata"
                        >
                          ℹ️
                        </span>
                        {sortCol === col.name ? (
                          <span className="text-brand-400" onClick={() => handleSort(col.name)}>{sortDir === 'asc' ? '↑' : '↓'}</span>
                        ) : (
                          <span className="text-slate-800 opacity-0 group-hover/th:opacity-100 transition-opacity" onClick={() => handleSort(col.name)}>↕</span>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row, i) => (
                  <tr key={row._row_index ?? `${page}-${i}`}>
                    <td className="text-center text-slate-600 font-mono text-[9px]">{page * PAGE_SIZE + i + 1}</td>
                    {visibleColumns.map(col => {
                      const val = getCellValue(row, col.name)
                      const isNull = val === null || val === undefined || val === ''
                      const modified = isCellModified(row, col.name)
                      const cellClass = modified ? 'bg-emerald-500/10 text-emerald-300 font-bold border border-emerald-500/25 glow-emerald-sm animate-pulse' : ''
                      return (
                        <td key={col.name} title={isNull ? 'null' : String(val)} className={cellClass}>
                          {editMode ? (
                            <input
                              value={String(val)}
                              onChange={e => setCellDraft(row._row_index, col.name, e.target.value)}
                              className="w-full bg-[#080d19] border border-white/10 rounded px-2 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:border-brand-500/40"
                            />
                          ) : isNull ? (
                            <span className="text-rose-500/50 italic text-[9px] font-sans pr-1">null</span>
                          ) : (
                            String(val)
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Row Pagination footer */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-5 py-2.5 border-t border-white/5 flex-shrink-0 bg-[#050811]/40 backdrop-blur select-none">
            <span className="text-[10px] text-slate-500 font-mono">
              Page {page + 1} of {totalPages}
            </span>
            <div className="flex gap-1.5">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="btn-ghost text-[10px] px-2.5 py-1 disabled:opacity-30 border border-white/5 bg-white/[0.01]"
              >
                ← Prev
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page === totalPages - 1}
                className="btn-ghost text-[10px] px-2.5 py-1 disabled:opacity-30 border border-white/5 bg-white/[0.01]"
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Column Metadata Inspector Drawer */}
      {selectedColumn && (
        <div className="w-80 border-l border-white/5 bg-[#050811]/90 backdrop-blur-xl h-full flex-shrink-0 flex flex-col animate-slide-in p-5 space-y-5 select-text overflow-y-auto custom-scrollbar">
          <div className="flex items-center justify-between border-b border-white/5 pb-3">
            <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              🛡️ Column Inspector
            </h3>
            <button
              onClick={() => setSelectedColumn(null)}
              className="text-slate-500 hover:text-slate-300 text-xs bg-transparent border-none outline-none cursor-pointer"
            >
              ✕
            </button>
          </div>

          <div className="space-y-4">
            {/* Spec details */}
            <div className="space-y-1.5">
              <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider">Header Field Name</span>
              <div className="text-xs font-bold text-rose-300 font-mono select-all truncate bg-rose-500/[0.02] border border-rose-500/10 rounded-xl px-3 py-2">
                {selectedColumn.name}
              </div>
            </div>

            <div className="space-y-1.5">
              <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider">Business Name</span>
              <div className="text-xs font-semibold text-slate-200 select-all truncate bg-white/[0.01] border border-white/5 rounded-xl px-3 py-2">
                {selectedColumn.label || selectedColumn.name}
              </div>
            </div>

            {/* Classification & Confidence Meter */}
            <div className="grid grid-cols-2 gap-3.5">
              <div className="space-y-1.5">
                <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider font-semibold">Domain Type</span>
                <span className="bg-brand-500/10 text-brand-300 border border-brand-500/10 px-2 py-1.5 rounded-xl text-[9px] font-bold uppercase tracking-wider block text-center truncate">
                  {selectedColumn.semantic_type || selectedColumn.dtype}
                </span>
              </div>

              <div className="space-y-1.5">
                <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider font-semibold">Confidence</span>
                <div className="flex items-center justify-center gap-1 bg-white/[0.01] border border-white/5 rounded-xl px-2 py-1.5 text-[9px] font-mono font-bold text-slate-300">
                  <div className={`w-2 h-2 rounded-full ${
                    (selectedColumn.confidence ?? 0.6) >= 0.8 ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]' :
                    (selectedColumn.confidence ?? 0.6) >= 0.6 ? 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.4)]' :
                    'bg-slate-500'
                  }`} />
                  {Math.round((selectedColumn.confidence ?? 0.6) * 100)}%
                </div>
              </div>
            </div>

            {/* Inferred Business Meaning */}
            <div className="space-y-1.5">
              <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider font-semibold">Inferred Meaning</span>
              <div className="text-[11px] text-slate-300 leading-relaxed bg-[#080d19] border border-white/5 rounded-xl p-3.5 select-text font-medium">
                {selectedColumn.inferred_meaning || 'General database parameter value.'}
              </div>
            </div>

            {/* Synonym Pills */}
            {selectedColumn.aliases?.length > 0 && (
              <div className="space-y-2">
                <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider block font-semibold">Suggested Synonym Aliases</span>
                <div className="flex flex-wrap gap-1.5">
                  {selectedColumn.aliases.map((alias, idx) => (
                    <span
                      key={idx}
                      className="bg-white/5 border border-white/5 hover:border-white/10 text-slate-400 px-2 py-1 rounded-lg text-[9px] font-mono cursor-pointer transition-all"
                    >
                      {alias}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Numeric Stats outline */}
            <div className="space-y-2.5 pt-2 border-t border-white/[0.03]">
              <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider block font-semibold">Column Specifications</span>
              <div className="text-[10px] space-y-1.5 font-mono">
                <div className="flex justify-between"><span className="text-slate-500">Data Type</span><span className="text-slate-300">{selectedColumn.dtype}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Missing Rows</span><span className="text-slate-300">{selectedColumn.null_count?.toLocaleString() || 0}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Unique Values</span><span className="text-slate-300">{selectedColumn.unique_count?.toLocaleString() || 0}</span></div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
