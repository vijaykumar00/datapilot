/**
 * Report builder: configure a branded report for the active dataset, preview
 * it as a page and download it as PDF, Word, PowerPoint or Excel.
 */
import { lazy, Suspense, useEffect, useState } from 'react'
import { AlertTriangle, Download, FileText, Loader2, Upload } from 'lucide-react'
import { useDataPilot } from '../../hooks/useDataPilot'
import { Badge, Button, EmptyState, ErrorState, PageHeader, Skeleton } from '../ui'
import { Segmented, SelectField, ViewPage, getBackendUrl, openUpload } from './shared'

const ReactMarkdown = lazy(() => import('react-markdown'))

// Brand colour presets. The hex values are sent to the backend, which uses
// them to theme the exported document and its charts.
const PRESETS = [
  { name: 'Indigo', primary: '#6366f1', secondary: '#a855f7' },
  { name: 'Emerald', primary: '#10b981', secondary: '#34d399' },
  { name: 'Amber', primary: '#f59e0b', secondary: '#fb923c' },
  { name: 'Rose', primary: '#f43f5e', secondary: '#fb7185' },
  { name: 'Slate', primary: '#64748b', secondary: '#94a3b8' },
]

const REPORT_TYPES = [
  { id: 'executive', label: 'Executive' },
  { id: 'operational', label: 'Operational' },
  { id: 'forecast', label: 'Forecast' },
]

const EXPORTS = [
  { format: 'pdf', label: 'PDF' },
  { format: 'docx', label: 'Word' },
  { format: 'pptx', label: 'PowerPoint' },
  { format: 'xlsx', label: 'Excel' },
]

const SEVERITY_TONE = { error: 'danger', warning: 'warning', success: 'success' }

function TextField({ id, label, value, onChange, placeholder }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="field-label">{label}</label>
      <input id={id} type="text" className="input h-10" value={value} onChange={onChange} placeholder={placeholder} />
    </div>
  )
}

function DocumentSkeleton() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Building report">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-7 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <div className="mt-2 flex flex-col gap-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <Skeleton className="h-48 w-full" />
      <p className="text-sm text-muted">Writing the summary and drawing the chart. This usually takes a few seconds.</p>
    </div>
  )
}

export default function ReportView() {
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
  const [genError, setGenError] = useState(null)
  const [exportError, setExportError] = useState(null)

  // Sync controls with active file
  useEffect(() => {
    if (activeFile) {
      const cols = activeFile.columns || []
      // Group by a readable category (e.g. region, product), not an ID column.
      const isNum = (c) => /int|float|double|num/.test(c.dtype || '')
      const isId = (c) => c.semantic_type === 'id' || /(^|_)id$|^id_/i.test(c.name || '')
      const categorical = cols.filter(c => !isNum(c) && !isId(c))
      const defaultX = (categorical.find(c => c.unique_count >= 2 && c.unique_count <= 50)
        || categorical.find(c => !/date|time/i.test(`${c.dtype} ${c.semantic_type} ${c.name}`))
        || categorical[0] || cols[0])?.name || ''
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
      setGenError(null)
    }
  }, [activeFile?.file_id, activeFile?.columns?.length, activeFile?.metadata?.restored])

  // No auto-generation: each report costs an AI call, so it runs only when the
  // user presses "Generate report".

  const handleGenerate = async () => {
    if (!activeFile) return
    setGenerating(true)
    setGenError(null)
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
        setGenError(data?.error || 'The report came back empty. Check the chart columns and try again.')
      }
    } catch (err) {
      setGenError(err?.message || 'The report could not be built. Try again in a moment.')
    } finally {
      setGenerating(false)
    }
  }

  const handleExport = async (format) => {
    if (!activeFile) return
    setExporting(format)
    setExportError(null)
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
      const res = await exportBespokeReport(options)
      if (res && res.success === false) {
        setExportError(`The download didn't start: ${res.error || 'please try again.'}`)
      }
    } catch (err) {
      setExportError(`The download didn't start: ${err?.message || 'please try again.'}`)
    } finally {
      setExporting(null)
    }
  }

  if (files.length === 0) {
    return (
      <ViewPage>
        <PageHeader
          title="Report builder"
          description="Turn a dataset into a branded report you can download as PDF, Word, PowerPoint or Excel."
        />
        <div className="card">
          <EmptyState
            icon={FileText}
            title="Upload a spreadsheet to build a report"
            description="Add a CSV or Excel file and Tallis will draft a summary, a chart and key figures for you."
            action={<Button variant="primary" icon={Upload} onClick={openUpload}>Upload data</Button>}
          />
        </div>
      </ViewPage>
    )
  }

  const reportTypeLabel = REPORT_TYPES.find(t => t.id === reportType)?.label || reportType
  const mdComponents = {
    // The page already has an h1; shift document headings down a level.
    h1: ({ node: _n, ...props }) => <h3 className="text-lg font-semibold" style={{ color: theme.primary }} {...props} />,
    h2: ({ node: _n, ...props }) => <h4 className="text-md font-semibold" style={{ color: theme.primary }} {...props} />,
    h3: ({ node: _n, ...props }) => <h5 className="text-base font-semibold text-fg" {...props} />,
  }

  return (
    <ViewPage>
      <PageHeader
        title="Report builder"
        description="Choose what the report covers, preview it, then download it in the format you need."
      />

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* Settings */}
        <section aria-labelledby="report-settings-heading" className="card lg:sticky lg:top-0">
          <div className="border-b border-line px-4 py-3 sm:px-5">
            <h2 id="report-settings-heading" className="text-md font-semibold text-fg">Report settings</h2>
          </div>
          <form
            className="flex flex-col gap-4 p-4 sm:p-5"
            onSubmit={(e) => { e.preventDefault(); handleGenerate() }}
          >
            {files.length > 1 && (
              <SelectField
                id="report-dataset"
                label="Dataset"
                value={activeFileId || activeFile.file_id}
                onChange={(e) => useDataPilot.getState().setActiveFileId(e.target.value)}
              >
                {files.map(f => <option key={f.file_id} value={f.file_id}>{f.filename}</option>)}
              </SelectField>
            )}

            <div className="flex flex-col gap-1">
              <span className="field-label" id="report-type-label">Report type</span>
              <Segmented label="Report type" options={REPORT_TYPES} value={reportType} onChange={setReportType} fill />
            </div>

            <TextField id="report-title" label="Title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Report title" />
            <TextField id="report-period" label="Period covered" value={dateRange} onChange={(e) => setDateRange(e.target.value)} placeholder="For example, Q1 2026" />

            <fieldset className="flex flex-col gap-1.5">
              <legend className="field-label mb-1.5">Brand colours</legend>
              <div role="radiogroup" aria-label="Brand colours" className="flex flex-wrap gap-2">
                {PRESETS.map((preset) => {
                  const active = theme.name === preset.name
                  return (
                    <button
                      key={preset.name}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      aria-label={preset.name}
                      data-tooltip={preset.name}
                      onClick={() => setTheme(preset)}
                      className={`flex h-10 w-10 overflow-hidden rounded-md border focus-ring ${
                        active ? 'border-fg ring-2 ring-primary ring-offset-2 ring-offset-surface' : 'border-line hover:border-line-strong'
                      }`}
                    >
                      <span className="h-full w-2/3" style={{ backgroundColor: preset.primary }} />
                      <span className="h-full w-1/3" style={{ backgroundColor: preset.secondary }} />
                    </button>
                  )
                })}
              </div>
              <p className="field-hint">Selected: {theme.name}</p>
            </fieldset>

            <div className="flex flex-col gap-3 border-t border-line pt-4">
              <div>
                <h3 className="text-base font-semibold text-fg">Chart</h3>
                <p className="text-sm text-muted">Pick the columns the report chart should compare.</p>
              </div>
              <SelectField id="report-chart-type" label="Chart type" value={chartType} onChange={(e) => setChartType(e.target.value)}>
                <option value="bar">Bar chart</option>
                <option value="line">Line chart</option>
                <option value="scatter">Scatter plot</option>
              </SelectField>
              <SelectField id="report-x-col" label="Group by (labels)" value={xCol} onChange={(e) => setXCol(e.target.value)}>
                {columns.map((c) => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
              </SelectField>
              <SelectField id="report-y-col" label="Measure (numbers)" value={yCol} onChange={(e) => setYCol(e.target.value)}>
                {columns.map((c) => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
              </SelectField>
            </div>

            <Button type="submit" variant="primary" icon={FileText} loading={generating} className="w-full">
              {generating ? 'Building report' : reportData ? 'Rebuild report' : 'Build report'}
            </Button>
          </form>
        </section>

        {/* Preview */}
        <section aria-labelledby="report-preview-heading" className="card min-w-0 overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="flex items-center gap-2">
              <h2 id="report-preview-heading" className="text-md font-semibold text-fg">Preview</h2>
              {generating && reportData && <Badge tone="info">Updating</Badge>}
            </div>
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Download report">
              {EXPORTS.map((btn) => {
                const isExp = exporting === btn.format
                return (
                  <button
                    key={btn.format}
                    type="button"
                    onClick={() => handleExport(btn.format)}
                    disabled={generating || exporting !== null}
                    aria-label={`Download as ${btn.label}`}
                    aria-busy={isExp || undefined}
                    className="btn-secondary btn-sm"
                  >
                    {isExp
                      ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      : <Download className="h-4 w-4" aria-hidden="true" />}
                    {btn.label}
                  </button>
                )
              })}
            </div>
          </div>

          {exportError && (
            <p role="alert" className="field-error mx-4 mt-3 flex items-start gap-1.5 sm:mx-5">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
              <span>{exportError}</span>
            </p>
          )}

          <div className="bg-sunken p-3 sm:p-6">
            {genError && (
              <ErrorState
                className="mx-auto mb-4 max-w-[210mm]"
                title="We couldn't build this report"
                description={genError}
                onRetry={handleGenerate}
              />
            )}

            <div className="mx-auto flex w-full max-w-[210mm] flex-col justify-between gap-8 rounded-md border border-line bg-surface p-5 sm:min-h-[297mm] sm:p-10">
              {generating && !reportData ? (
                <DocumentSkeleton />
              ) : reportData ? (
                <>
                  <div className="flex min-w-0 flex-col gap-6">
                    {/* Masthead */}
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M12 2L2 7L12 12L22 7L12 2Z" fill={theme.primary} />
                            <path d="M2 17L12 22L22 17" stroke={theme.secondary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M2 12L12 17L22 12" stroke={theme.primary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          <span className="text-sm font-semibold text-fg">Tallis</span>
                        </div>
                        <span className="text-xs text-subtle">Confidential · {reportTypeLabel} report</span>
                      </div>
                      <div className="flex h-1 w-full overflow-hidden rounded-full" aria-hidden="true">
                        <span className="w-2/3" style={{ backgroundColor: theme.primary }} />
                        <span className="w-1/3" style={{ backgroundColor: theme.secondary }} />
                      </div>
                    </div>

                    <div className="flex flex-col gap-1">
                      <p className="break-words text-2xl font-semibold" style={{ color: theme.primary }}>
                        {reportData.title || title}
                      </p>
                      <p className="text-sm text-muted">
                        {reportData.date_range || 'All periods'} · Prepared with Tallis
                      </p>
                    </div>

                    <div className="flex flex-col gap-2">
                      <h3 className="text-base font-semibold text-fg">1. Summary</h3>
                      <div className="prose-dp min-w-0 max-w-none break-words text-base">
                        <Suspense fallback={<p className="whitespace-pre-wrap">{reportData.narrative || ''}</p>}>
                          <ReactMarkdown components={mdComponents}>
                            {reportData.narrative || ''}
                          </ReactMarkdown>
                        </Suspense>
                      </div>
                    </div>

                    {reportData.chart_url && (
                      <figure className="flex flex-col gap-2">
                        <h3 className="text-base font-semibold text-fg">2. Chart</h3>
                        <div className="flex justify-center rounded-md border border-line bg-surface-muted p-2">
                          <img
                            src={getBackendUrl(reportData.chart_url)}
                            alt={`Chart of ${yCol} by ${xCol}`}
                            className="max-h-72 w-auto max-w-full object-contain"
                          />
                        </div>
                        <figcaption className="text-center text-xs text-subtle">
                          {yCol} by {xCol}
                        </figcaption>
                      </figure>
                    )}

                    {reportData.kpis && reportData.kpis.length > 0 && (
                      <div className="flex flex-col gap-2">
                        <h3 className="text-base font-semibold text-fg">{reportData.chart_url ? '3.' : '2.'} Key figures</h3>
                        <div className="overflow-x-auto rounded-md border border-line" style={{ borderTopColor: theme.primary, borderTopWidth: 2 }}>
                          <table className="data-table w-full">
                            <thead>
                              <tr>
                                <th scope="col">Measure</th>
                                <th scope="col" className="is-number">Value</th>
                                <th scope="col" className="is-number">Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {reportData.kpis.map((kpi, idx) => (
                                <tr key={idx}>
                                  <td className="font-medium text-fg">{kpi.title}</td>
                                  <td className="is-number tabular">{kpi.metric}</td>
                                  <td className="is-number">
                                    <Badge tone={SEVERITY_TONE[kpi.severity] || 'info'}>{kpi.severity || 'info'}</Badge>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs text-subtle">
                    <span>Confidential</span>
                    <span>Page 1 of 1</span>
                  </div>
                </>
              ) : (
                <EmptyState
                  className="my-auto"
                  icon={FileText}
                  title="Ready to build"
                  description={`Your report for "${activeFile.filename}" will appear here. Adjust the settings, then build it.`}
                  action={<Button variant="primary" icon={FileText} onClick={handleGenerate} loading={generating}>Build report</Button>}
                />
              )}
            </div>
          </div>
        </section>
      </div>
    </ViewPage>
  )
}
