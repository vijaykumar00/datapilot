/**
 * Insights: AI-generated profile cards for the active dataset plus every
 * chart produced in the conversation.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, BarChart3, Check, ChevronDown, ChevronUp, Columns3, Copy, Lightbulb,
  LineChart, Link2, MessageSquare, RefreshCw, Rows3, ShieldAlert, Sigma, Sparkles, TrendingUp, Upload,
} from 'lucide-react'
import { useDataPilot } from '../../hooks/useDataPilot'
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton } from '../ui'
import { LazyChart, Segmented, SelectField, ViewPage, chartCaption, openUpload } from './shared'

const CATEGORIES = [
  { id: 'all', label: 'All', icon: Sparkles },
  { id: 'statistical', label: 'Statistical', icon: Sigma },
  { id: 'trend', label: 'Trend', icon: TrendingUp },
  { id: 'quality', label: 'Quality', icon: ShieldAlert },
  { id: 'forecast', label: 'Forecast', icon: LineChart },
  { id: 'relationship', label: 'Relationship', icon: Link2 },
]

const CATEGORY_ICON = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.icon]))

const SEVERITY = {
  error: { tone: 'danger', label: 'Issue', bar: 'bg-danger' },
  warning: { tone: 'warning', label: 'Warning', bar: 'bg-warning' },
  success: { tone: 'success', label: 'Good', bar: 'bg-success' },
  info: { tone: 'info', label: 'Info', bar: 'bg-info' },
}

function StatTile({ icon: Icon, label, value, tone = 'text-fg' }) {
  return (
    <div className="card card-pad flex min-w-0 flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm text-muted">{label}</span>
        <Icon className="h-4 w-4 flex-shrink-0 text-subtle" aria-hidden="true" />
      </div>
      <span className={`tabular truncate text-2xl font-semibold ${tone}`}>{value}</span>
    </div>
  )
}

function InsightCard({ insight, idx, isSqlOpen, isCopied, onToggleSql, onCopy }) {
  const isObj = insight && typeof insight === 'object'
  const id = isObj ? (insight.id || `idx_${idx}`) : `str_${idx}`
  const type = isObj ? (insight.type || 'statistical') : 'statistical'
  const titleText = isObj ? (insight.title || '') : insight
  const descriptionText = isObj ? (insight.description || '') : ''
  const severity = isObj ? (insight.severity || 'info') : 'info'
  const metric = isObj ? (insight.metric || '') : ''
  const sqlText = isObj ? (insight.sql || '') : ''
  const chartType = isObj ? (insight.chart_type || '') : ''

  const sev = SEVERITY[severity] || SEVERITY.info
  const TypeIcon = CATEGORY_ICON[type] || Lightbulb
  const sqlId = `insight-sql-${id}`

  return (
    <article className="card relative flex min-w-0 flex-col gap-3 overflow-hidden p-4 pl-5">
      <span className={`absolute inset-y-0 left-0 w-1 ${sev.bar}`} aria-hidden="true" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <TypeIcon className="h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
          <span className="truncate text-sm capitalize text-muted">{type}</span>
          <Badge tone={sev.tone}>{sev.label}</Badge>
        </div>
        {metric && <span className="chip tabular max-w-full truncate">{metric}</span>}
      </div>

      <div className="min-w-0 space-y-1">
        <h3 className="break-words text-md font-semibold text-fg">{titleText}</h3>
        {descriptionText && <p className="break-words text-base text-muted">{descriptionText}</p>}
      </div>

      {sqlText && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => onToggleSql(isSqlOpen ? null : id)}
              aria-expanded={isSqlOpen}
              aria-controls={sqlId}
              className="inline-flex items-center gap-1 rounded text-sm font-medium text-primary-text hover:underline focus-ring"
            >
              {isSqlOpen
                ? <ChevronUp className="h-4 w-4" aria-hidden="true" />
                : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
              {isSqlOpen ? 'Hide the SQL behind this' : 'Show the SQL behind this'}
            </button>
            {chartType && <span className="text-xs text-subtle">Suggested chart: {chartType}</span>}
          </div>

          {isSqlOpen && (
            <div id={sqlId} className="relative rounded-md border border-line bg-sunken">
              <Button
                size="sm"
                variant="ghost"
                icon={isCopied ? Check : Copy}
                onClick={() => onCopy(id, sqlText)}
                className="absolute right-1.5 top-1.5"
              >
                {isCopied ? 'Copied' : 'Copy'}
              </Button>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words p-3 pr-24 font-mono text-xs text-fg">{sqlText}</pre>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

export default function DashboardView({ ChartRenderer }) {
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
    try {
      if (activeSheet) {
        await switchSheet(activeFile.file_id, activeSheet)
      } else {
        await loadPreviewFile(activeFile.file_id)
      }
    } finally {
      setIsRegenerating(false)
    }
  }

  const handleCopySql = (id, sqlText) => {
    Promise.resolve(navigator.clipboard?.writeText(sqlText)).catch(() => {})
    setCopiedCardId(id)
    setTimeout(() => setCopiedCardId(null), 2000)
  }

  const filteredInsights = activeCategory === 'all'
    ? insights
    : insights.filter(i => i?.type === activeCategory)

  const anomaliesCount = insights.filter(i => i?.severity === 'warning' || i?.severity === 'error').length

  const categoryOptions = CATEGORIES.map((cat) => ({
    ...cat,
    count: cat.id === 'all' ? insights.length : insights.filter(i => i?.type === cat.id).length,
  }))

  const toolbar = activeFile && (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
      {files.length > 1 && (
        <SelectField
          id="insights-dataset"
          label="Dataset"
          value={activeFileId || activeFile.file_id}
          onChange={(e) => useDataPilot.getState().setActiveFileId(e.target.value)}
          className="sm:w-64"
        >
          {files.map(f => <option key={f.file_id} value={f.file_id}>{f.filename}</option>)}
        </SelectField>
      )}
      {sheets.length > 1 && (
        <SelectField
          id="insights-sheet"
          label="Sheet"
          value={activeSheet || sheets[0]}
          onChange={(e) => handleSheetChange(e.target.value)}
          className="sm:w-48"
        >
          {sheets.map(sh => <option key={sh} value={sh}>{sh}</option>)}
        </SelectField>
      )}
      <Button icon={RefreshCw} loading={isRegenerating} onClick={handleRegenerate} className="h-10 self-start sm:self-auto">
        {isRegenerating ? 'Refreshing insights' : 'Refresh insights'}
      </Button>
    </div>
  )

  return (
    <ViewPage>
      <PageHeader
        title="Insights"
        description="Patterns, trends and data quality issues Tallis found in your data, plus every chart from your conversations."
      />
      {toolbar}

      {!activeFile ? (
        <div className="card">
          <EmptyState
            icon={Upload}
            title="Upload a spreadsheet to see insights"
            description="Tallis profiles each CSV or Excel file you add and lists what stands out."
            action={<Button variant="primary" icon={Upload} onClick={openUpload}>Upload data</Button>}
          />
        </div>
      ) : (
        <>
          <section aria-label="Dataset summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile icon={Rows3} label="Rows" value={activeFile.row_count?.toLocaleString() || 0} />
            <StatTile icon={Columns3} label="Columns" value={activeFile.column_count || 0} />
            <StatTile
              icon={AlertTriangle}
              label="Quality issues"
              value={anomaliesCount}
              tone={anomaliesCount > 0 ? 'text-warning' : 'text-fg'}
            />
            <StatTile icon={BarChart3} label="Charts" value={charts.length} />
          </section>

          {anomaliesCount > 0 && (
            <div role="status" className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-soft p-4">
              <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-warning" aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-base font-semibold text-fg">
                  {anomaliesCount === 1 ? '1 data quality issue needs a look' : `${anomaliesCount} data quality issues need a look`}
                </p>
                <p className="mt-0.5 text-sm text-muted">
                  Duplicates, extreme outliers or clusters of empty cells can skew your totals and averages.
                  Review the cards below, or ask the assistant to clean the data.
                </p>
              </div>
            </div>
          )}

          <section aria-labelledby="insights-heading" className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <h2 id="insights-heading" className="text-lg font-semibold text-fg">What stands out</h2>
              <Segmented
                label="Filter insights by type"
                options={categoryOptions}
                value={activeCategory}
                onChange={(id) => { setActiveCategory(id); setShowSqlCardId(null) }}
              />
            </div>

            {isRegenerating ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-hidden="true">
                {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36 rounded-lg" />)}
              </div>
            ) : filteredInsights.length > 0 ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {filteredInsights.map((insight, idx) => {
                  const id = insight && typeof insight === 'object' ? (insight.id || `idx_${idx}`) : `str_${idx}`
                  return (
                    <InsightCard
                      key={id}
                      insight={insight}
                      idx={idx}
                      isSqlOpen={showSqlCardId === id}
                      isCopied={copiedCardId === id}
                      onToggleSql={setShowSqlCardId}
                      onCopy={handleCopySql}
                    />
                  )
                })}
              </div>
            ) : (
              <div className="card">
                <EmptyState
                  compact
                  icon={Lightbulb}
                  title={activeCategory === 'all' ? 'No insights yet' : 'No insights of this type'}
                  description={activeCategory === 'all'
                    ? 'Refresh insights to profile this dataset again.'
                    : 'Pick another type above, or refresh insights to profile the dataset again.'}
                  action={<Button size="sm" icon={RefreshCw} onClick={handleRegenerate}>Refresh insights</Button>}
                />
              </div>
            )}
          </section>
        </>
      )}

      <section aria-labelledby="charts-heading" className="flex flex-col gap-3">
        <h2 id="charts-heading" className="text-lg font-semibold text-fg">Charts from your conversations</h2>
        {charts.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {charts.map((msg, idx) => {
              const caption = msg.content ? chartCaption(msg.content, 180) : ''
              return (
                <Card
                  key={msg.id || idx}
                  title={`Chart ${idx + 1}`}
                  actions={msg.ts ? <span className="text-xs text-subtle">{new Date(msg.ts).toLocaleTimeString()}</span> : null}
                  className="min-w-0"
                  bodyClassName="flex flex-col gap-3 p-3 sm:p-4"
                >
                  <div className="min-w-0 overflow-hidden rounded-md border border-line bg-surface">
                    <LazyChart ChartRenderer={ChartRenderer} spec={msg.chart_data} />
                  </div>
                  {caption && <p className="break-words text-sm text-muted">{caption}</p>}
                </Card>
              )
            })}
          </div>
        ) : (
          <div className="card">
            <EmptyState
              compact
              icon={BarChart3}
              title="No charts yet"
              description='Ask the assistant something like "Chart revenue by month" and the chart will appear here.'
              action={<Link to="/app/analyze" className="btn-secondary btn-sm"><MessageSquare className="h-4 w-4" aria-hidden="true" />Ask a question</Link>}
            />
          </div>
        )}
      </section>
    </ViewPage>
  )
}
