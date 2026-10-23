import { useEffect, useMemo, useState } from 'react'
import {
  AlertCircle, AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, AtSign, Calendar, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  CircleDollarSign, Download, FileSpreadsheet, Hash, Info, Pencil, Percent, Save, Search, Table2, ToggleLeft, Type, Undo2, Upload, Wand2, X, XCircle,
} from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { Button, EmptyState, ErrorState, IconButton, Spinner, cx } from './ui'

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
    setPreviewFile,
  } = useDataPilot()
  const [notice, setNotice] = useState('')

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
    if (!file?.file_id || previewLoading || previewError) return
    // Files restored after a reload carry only metadata: fetch their rows once.
    const needsRows = !file.sample_data || (rows.length > 0 && rows.some(row => row._row_index === undefined))
    if (needsRows) loadPreviewFile(file.file_id)
  }, [file?.file_id, file?.sample_data, rows, loadPreviewFile, previewLoading, previewError])

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
      setNotice(result?.error || `Could not export ${format === 'xlsx' ? 'Excel' : 'CSV'}. Try again.`)
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
      setNotice(result.error || 'Could not undo the last change. Try again.')
    }
  }

  const isCellModified = (row, columnName) => {
    if (!transformationPlan || previewTab !== 'after') return false
    const rowIndex = row._row_index
    const beforeRow = transformationPlan.preview_before.rows.find(r => r._row_index === rowIndex)
    if (!beforeRow) return false
    return String(beforeRow[columnName] ?? '') !== String(row[columnName] ?? '')
  }


  const isNumericCol = (col) => /int|float|double|decimal|number/i.test(col?.dtype || '') || ['currency', 'percentage', 'numeric', 'number'].includes(col?.semantic_type)
  const typeLabel = (col) => {
    const s = col?.semantic_type
    if (s && s !== 'text' && s !== 'empty') return s.charAt(0).toUpperCase() + s.slice(1)
    if (isNumericCol(col)) return 'Number'
    if (/date|time/i.test(col?.dtype || '')) return 'Date'
    if (/bool/i.test(col?.dtype || '')) return 'Yes/No'
    return 'Text'
  }
  const TypeIcon = ({ col, className = 'h-3.5 w-3.5' }) => {
    const t = typeLabel(col)
    const I = t === 'Currency' ? CircleDollarSign : t === 'Percentage' ? Percent : t === 'Number' ? Hash : (t === 'Date' || t === 'Datetime') ? Calendar : t === 'Email' ? AtSign : t === 'Yes/No' ? ToggleLeft : Type
    return <I className={className} aria-hidden="true" />
  }

  if (previewLoading || transformLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-bg p-8 text-center" aria-live="polite">
        <Spinner className="h-6 w-6 text-primary-text" label="Loading" />
        <p className="text-base text-muted">{transformLoading ? 'Working on your changes…' : 'Loading your data…'}</p>
      </div>
    )
  }

  if (previewError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg p-6">
        <ErrorState title="Could not load this file" description={previewError} onRetry={previewFileId ? () => loadPreviewFile(previewFileId) : undefined} />
      </div>
    )
  }

  if (!file) {
    return (
      <div className="flex h-full items-center justify-center bg-bg p-6">
        <div className="w-full max-w-md">
          <EmptyState
            icon={Table2}
            title={files.length ? 'Choose a file to open' : 'No data to show yet'}
            description={files.length ? 'Pick one of your files to see its rows and columns.' : 'Upload a CSV or Excel file to see it here as a spreadsheet.'}
            action={files.length ? null : <Button variant="primary" icon={Upload} onClick={() => window.dispatchEvent(new CustomEvent('dp:open-upload'))}>Upload data</Button>}
          />
          {files.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1.5">
              {files.map((f) => (
                <li key={f.file_id}>
                  <button type="button" onClick={() => setPreviewFile(f.file_id)} className="flex min-h-[44px] w-full items-center gap-3 rounded-md border border-line bg-surface px-3 py-2 text-left hover:border-line-strong focus-ring">
                    <FileSpreadsheet className="h-4 w-4 flex-shrink-0 text-subtle" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate text-base font-medium text-fg">{f.filename}</span>
                    {f.row_count != null && <span className="tabular text-sm text-subtle">{f.row_count.toLocaleString()} rows</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    )
  }

  const lastWorkflow = file?.metadata?.applied_workflows?.[file.metadata.applied_workflows.length - 1]
  const severityIcon = { error: XCircle, warning: AlertTriangle, success: CheckCircle2 }
  const severityTone = { error: 'text-danger', warning: 'text-warning', success: 'text-success' }

  return (
    <div className="relative flex h-full w-full overflow-hidden bg-bg">
      <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex flex-shrink-0 flex-col gap-3 border-b border-line bg-surface px-4 py-3 sm:px-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <h2 className="flex min-w-0 items-center gap-2 text-lg font-semibold text-fg">
              <FileSpreadsheet className="h-[18px] w-[18px] flex-shrink-0 text-subtle" aria-hidden="true" />
              <span className="truncate" title={file.filename}>{file.filename}</span>
            </h2>
            <p className="tabular mt-0.5 text-sm text-muted">
              {file.row_count?.toLocaleString()} rows · {file.column_count} columns
              {filter && ` · ${processed.length.toLocaleString()} shown`}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1 sm:w-56 sm:flex-none">
              <label htmlFor="preview-search" className="sr-only">Search rows</label>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden="true" />
              <input id="preview-search" type="search" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(0) }} placeholder="Search rows" className="input h-9 pl-9" />
            </div>
            {lastWorkflow && (
              <Button size="sm" variant="secondary" icon={Undo2} onClick={handleUndoTransform} title={`Undo: ${lastWorkflow.description}`}>Undo change</Button>
            )}
            <Button size="sm" variant={showWorkflowInput ? 'primary' : 'secondary'} icon={Wand2} aria-pressed={showWorkflowInput} onClick={() => setShowWorkflowInput(!showWorkflowInput)}>Clean with AI</Button>
            {editMode ? (
              <>
                <Button size="sm" variant="primary" icon={Save} onClick={handleSave} disabled={!draftCount} loading={previewSaving}>
                  {previewSaving ? 'Saving' : `Save${draftCount ? ` ${draftCount} change${draftCount === 1 ? '' : 's'}` : ''}`}
                </Button>
                <Button size="sm" variant="ghost" onClick={handleCancel}>Cancel</Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setEditMode(true)}>Edit values</Button>
            )}
            <Button size="sm" variant="ghost" icon={Download} onClick={() => handleExport('csv')}>CSV</Button>
            <Button size="sm" variant="ghost" icon={Download} onClick={() => handleExport('xlsx')}>Excel</Button>
          </div>
        </div>

        {notice && (
          <div className="flex flex-shrink-0 items-start gap-2 border-b border-danger/30 bg-danger-soft px-4 py-2 text-sm text-danger sm:px-5" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
            <span className="flex-1">{notice}</span>
            <button type="button" className="font-medium underline" onClick={() => setNotice('')}>Dismiss</button>
          </div>
        )}

        {/* AI clean-up request */}
        {showWorkflowInput && !transformationPlan && (
          <form
            className="flex flex-shrink-0 flex-col gap-2 border-b border-line bg-surface-muted px-4 py-3 sm:px-5"
            onSubmit={(e) => { e.preventDefault(); handleProposeWorkflow() }}
          >
            <label htmlFor="workflow-input" className="text-base font-medium text-fg">Describe the change you want</label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                id="workflow-input"
                type="text"
                value={workflowQuery}
                onChange={(e) => setWorkflowQuery(e.target.value)}
                placeholder="For example: remove empty rows, or keep only orders above 2,000"
                className="input flex-1"
                aria-describedby={transformError ? 'workflow-error' : 'workflow-hint'}
                aria-invalid={!!transformError || undefined}
              />
              <Button type="submit" variant="primary" disabled={!workflowQuery.trim()}>Preview changes</Button>
            </div>
            {transformError
              ? <p id="workflow-error" className="field-error" role="alert">{transformError}</p>
              : <p id="workflow-hint" className="field-hint">You will see a before and after preview. Nothing changes until you apply it.</p>}
          </form>
        )}

        {/* Proposed change preview */}
        {transformationPlan && (
          <div className="flex flex-shrink-0 flex-col gap-3 border-b border-line bg-surface-muted px-4 py-3 sm:px-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-base font-medium text-fg">Review proposed changes</p>
                <p className="text-sm text-muted">
                  About <strong className="tabular font-semibold text-fg">{transformationPlan.affected_rows?.toLocaleString()} rows</strong> in this preview will change. Changed cells are highlighted.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div role="tablist" aria-label="Preview version" className="inline-flex rounded-md border border-line bg-surface p-0.5">
                  {[['before', 'Before'], ['after', 'After']].map(([k, l]) => (
                    <button key={k} type="button" role="tab" aria-selected={previewTab === k} onClick={() => setPreviewTab(k)}
                      className={cx('h-8 rounded px-3 text-sm font-medium', previewTab === k ? 'bg-primary-soft text-primary-text' : 'text-muted hover:text-fg')}>{l}</button>
                  ))}
                </div>
                <Button size="sm" variant="primary" icon={Check} onClick={handleApplyWorkflow}>Apply changes</Button>
                <Button size="sm" variant="ghost" icon={X} onClick={handleDiscardWorkflow}>Discard</Button>
              </div>
            </div>
            {transformationPlan.actions?.length > 0 && (
              <ol className="flex flex-col gap-1 text-sm text-fg">
                {transformationPlan.actions.map((act, idx) => (
                  <li key={idx} className="flex gap-2">
                    <span className="tabular w-5 flex-shrink-0 text-right text-subtle">{idx + 1}.</span>
                    <span>{act.description}</span>
                  </li>
                ))}
              </ol>
            )}
            {transformError && <p className="field-error" role="alert">{transformError}</p>}
          </div>
        )}

        {/* Data notes */}
        {file.metadata?.insights?.length > 0 && (
          <div className="flex-shrink-0 border-b border-line px-4 py-2 sm:px-5">
            <button type="button" onClick={() => setShowInsights((p) => !p)} aria-expanded={showInsights}
              className="flex min-h-[32px] items-center gap-1.5 text-sm font-medium text-muted hover:text-fg">
              <ChevronDown className={cx('h-4 w-4 transition-transform', !showInsights && '-rotate-90')} aria-hidden="true" />
              Notes about this data ({Math.min(4, file.metadata.insights.length)})
            </button>
            {showInsights && (
              <ul className="mt-1.5 grid grid-cols-1 gap-2 pb-1 sm:grid-cols-2 xl:grid-cols-4">
                {file.metadata.insights.slice(0, 4).map((insight, idx) => {
                  const I = severityIcon[insight?.severity] || Info
                  const text = insight?.title || (typeof insight === 'string' ? insight : '')
                  return (
                    <li key={insight?.id || idx} className="flex gap-2 rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg">
                      <I className={cx('mt-0.5 h-4 w-4 flex-shrink-0', severityTone[insight?.severity] || 'text-info')} aria-hidden="true" />
                      <span>{text}</span>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )}

        {/* Grid */}
        <div className="min-h-0 flex-1 overflow-auto overscroll-contain" tabIndex={0} aria-label={`${file.filename} data`} role="region">
          {pageRows.length === 0 ? (
            <div className="flex h-full items-center justify-center p-6">
              <EmptyState compact icon={Search} title="No rows match" description={filter ? `Nothing matches “${filter}”.` : 'This file has no rows to show.'}
                action={filter ? <Button size="sm" onClick={() => { setFilter(''); setPage(0) }}>Clear search</Button> : null} />
            </div>
          ) : (
            <table className="data-table">
              <caption className="sr-only">{file.filename}, page {page + 1} of {Math.max(1, totalPages)}</caption>
              <thead>
                <tr>
                  <th scope="col" className="w-12 text-right text-subtle">#</th>
                  {visibleColumns.map((col) => {
                    const sorted = sortCol === col.name
                    const SortIcon = sorted ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
                    return (
                      <th key={col.name} scope="col" aria-sort={sorted ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} className={cx(isNumericCol(col) && 'is-number')}>
                        <div className={cx('flex items-center gap-1', isNumericCol(col) && 'justify-end')}>
                          <button type="button" onClick={() => handleSort(col.name)} className="group flex min-w-0 items-center gap-1.5 rounded text-left hover:text-fg focus-ring" title={`Sort by ${col.label || col.name}`}>
                            <span className="text-subtle" title={typeLabel(col)}><TypeIcon col={col} /></span>
                            <span className="truncate">{col.label || col.name}</span>
                            <SortIcon className={cx('h-3.5 w-3.5 flex-shrink-0', sorted ? 'text-primary-text' : 'text-subtle opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100')} aria-hidden="true" />
                          </button>
                          <button type="button" onClick={() => setSelectedColumn(col)} className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded text-subtle hover:bg-surface-muted hover:text-fg focus-ring" aria-label={`About column ${col.label || col.name}`}>
                            <Info className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </div>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row, i) => (
                  <tr key={row._row_index ?? `${page}-${i}`}>
                    <td className="tabular text-right text-sm text-subtle">{page * PAGE_SIZE + i + 1}</td>
                    {visibleColumns.map((col) => {
                      const val = getCellValue(row, col.name)
                      const isNull = val === null || val === undefined || val === ''
                      const modified = isCellModified(row, col.name)
                      return (
                        <td key={col.name} title={isNull ? 'Empty' : String(val)} className={cx(isNumericCol(col) && 'is-number', modified && 'bg-success-soft font-medium text-fg')}>
                          {editMode ? (
                            <input
                              value={String(val)}
                              onChange={(e) => setCellDraft(row._row_index, col.name, e.target.value)}
                              aria-label={`${col.label || col.name}, row ${page * PAGE_SIZE + i + 1}`}
                              className="input h-8 min-w-[6rem] px-2 py-0 text-sm"
                            />
                          ) : isNull ? (
                            <span className="text-sm italic text-subtle">empty</span>
                          ) : (
                            String(val)
                          )}
                          {modified && <span className="sr-only"> (changed)</span>}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {totalPages > 1 && (
          <nav aria-label="Pages" className="flex flex-shrink-0 items-center justify-between gap-2 border-t border-line bg-surface px-4 py-2 pb-safe sm:px-5">
            <span className="tabular text-sm text-muted">Page {page + 1} of {totalPages}</span>
            <div className="flex gap-1.5">
              <Button size="sm" variant="secondary" icon={ChevronLeft} onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>Previous</Button>
              <Button size="sm" variant="secondary" onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}>
                Next <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </nav>
        )}
      </div>

      {/* Column details */}
      {selectedColumn && (
        <>
          <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" aria-hidden="true" onClick={() => setSelectedColumn(null)} />
          <aside
            aria-label="Column details"
            className="fixed inset-y-0 right-0 z-40 flex w-full max-w-sm flex-col overflow-y-auto border-l border-line bg-surface pb-safe lg:static lg:z-auto lg:w-80 lg:flex-shrink-0"
          >
            <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-3">
              <h3 className="flex min-w-0 items-center gap-2 text-md font-semibold text-fg">
                <TypeIcon col={selectedColumn} className="h-4 w-4 flex-shrink-0 text-subtle" />
                <span className="truncate">{selectedColumn.label || selectedColumn.name}</span>
              </h3>
              <IconButton icon={X} label="Close column details" onClick={() => setSelectedColumn(null)} tooltipSide="left" />
            </div>
            <div className="flex flex-col gap-5 p-5">
              <p className="text-base text-fg">{selectedColumn.inferred_meaning || 'No description has been inferred for this column yet.'}</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-base">
                <dt className="text-muted">Column name</dt><dd className="truncate text-right font-mono text-sm text-fg select-all">{selectedColumn.name}</dd>
                <dt className="text-muted">Type</dt><dd className="text-right text-fg">{typeLabel(selectedColumn)}</dd>
                <dt className="text-muted">Stored as</dt><dd className="text-right font-mono text-sm text-fg">{selectedColumn.dtype}</dd>
                <dt className="text-muted">Empty cells</dt>
                <dd className={cx('tabular text-right', selectedColumn.null_count > 0 ? 'text-warning' : 'text-fg')}>{(selectedColumn.null_count || 0).toLocaleString()}</dd>
                <dt className="text-muted">Unique values</dt><dd className="tabular text-right text-fg">{(selectedColumn.unique_count || 0).toLocaleString()}</dd>
                <dt className="text-muted">Type confidence</dt>
                <dd className="tabular text-right text-fg">
                  {Math.round((selectedColumn.confidence ?? 0.6) * 100)}%
                  <span className="ml-1 text-sm text-muted">({(selectedColumn.confidence ?? 0.6) >= 0.8 ? 'high' : (selectedColumn.confidence ?? 0.6) >= 0.6 ? 'medium' : 'low'})</span>
                </dd>
              </dl>
              {selectedColumn.aliases?.length > 0 && (
                <div>
                  <p className="mb-1.5 text-sm font-medium text-muted">Also understood as</p>
                  <ul className="flex flex-wrap gap-1.5">
                    {selectedColumn.aliases.map((alias, idx) => <li key={idx} className="chip">{alias}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  )
}
