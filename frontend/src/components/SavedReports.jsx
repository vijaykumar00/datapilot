import { useState, useEffect, useMemo, useId } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  AlertCircle, ArrowLeft, CalendarClock, FileText, MessageSquare, Pencil, Plus, RefreshCw, Search, Star, Trash2,
} from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { apiUrl } from '../lib/apiConfig'
import { Badge, Button, EmptyState, ErrorState, IconButton, PageHeader, Skeleton, cx } from './ui'
import Dialog from './ui/Dialog'

function formatRelativeTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? '' : 'Z'))
  if (Number.isNaN(d.getTime())) return '—'
  const mins = Math.floor((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days} d ago`
  return d.toLocaleDateString()
}

function tagsOf(report) {
  if (Array.isArray(report?.tags)) return report.tags
  if (typeof report?.tags === 'string' && report.tags) {
    try { const v = JSON.parse(report.tags); return Array.isArray(v) ? v : [] } catch { return report.tags.split(',').map(t => t.trim()).filter(Boolean) }
  }
  return []
}

const getBackendUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return apiUrl(path)
}

const SEVERITY_TONE = { high: 'danger', critical: 'danger', medium: 'warning', warning: 'warning', low: 'success', info: 'info' }

export default function SavedReports() {
  const navigate = useNavigate()
  const {
    reports,
    reportsLoading,
    loadReports,
    updateReport,
    deleteReport,
    reportVersions,
    reportVersionsLoading,
    loadReportVersions,
    createReportVersion,
  } = useDataPilot()

  const [selectedReportId, setSelectedReportId] = useState(null)
  const [activeVersionId, setActiveVersionId] = useState(null)
  const [search, setSearch] = useState('')
  const [starredOnly, setStarredOnly] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')

  // Edit forms
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editScheduled, setEditScheduled] = useState(false)
  const [editCron, setEditCron] = useState('')
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState('')
  const [editTitleError, setEditTitleError] = useState('')

  // New version form
  const [newVersionContent, setNewVersionContent] = useState('')
  const [showVersionForm, setShowVersionForm] = useState(false)
  const [versionSaving, setVersionSaving] = useState(false)
  const [versionError, setVersionError] = useState('')

  const ids = {
    search: useId(), versionSelect: useId(), title: useId(), titleErr: useId(), tags: useId(), tagsHint: useId(),
    desc: useId(), scheduled: useId(), cron: useId(), cronHint: useId(), content: useId(), contentHint: useId(),
  }

  const reload = async () => {
    setLoadError('')
    const res = await loadReports()
    if (res && res.success === false) setLoadError(res.error || 'The server did not respond.')
  }

  useEffect(() => {
    reload()
  }, [])

  const selectedReport = useMemo(() => {
    return (reports || []).find(r => r.report_id === selectedReportId) || null
  }, [reports, selectedReportId])

  // Automatically load versions when selected report changes
  useEffect(() => {
    if (selectedReportId) {
      loadReportVersions(selectedReportId)
      setIsEditing(false)
      setShowVersionForm(false)
    }
  }, [selectedReportId])

  // Select active version (default to latest report details)
  const activeVersion = useMemo(() => {
    if (!selectedReport) return null
    if (!activeVersionId) return selectedReport
    return reportVersions.find(v => v.report_id === activeVersionId) || selectedReport
  }, [selectedReport, reportVersions, activeVersionId])

  const filtered = useMemo(() => {
    return (reports || []).filter(r => {
      if (starredOnly && !r.starred) return false
      if (search) {
        const q = search.toLowerCase()
        if (
          !(r.title || '').toLowerCase().includes(q) &&
          !(r.description || '').toLowerCase().includes(q) &&
          !tagsOf(r).join(' ').toLowerCase().includes(q)
        ) return false
      }
      return true
    })
  }, [reports, search, starredOnly])

  const total = reports?.length || 0

  const selectReport = (reportId) => {
    setSelectedReportId(reportId)
    setActiveVersionId(null)
  }

  const handleStar = async (report) => {
    setActionError('')
    const res = await updateReport(report.report_id, { starred: !report.starred })
    if (res && res.success === false) setActionError('Could not update the star. Check your connection and try again.')
  }

  const handleEditClick = () => {
    if (!selectedReport) return
    setEditTitle(selectedReport.title || '')
    setEditDesc(selectedReport.description || '')
    setEditTags(tagsOf(selectedReport).join(', '))
    setEditScheduled(Boolean(selectedReport.scheduled))
    setEditCron(selectedReport.schedule_cron || '')
    setEditError('')
    setEditTitleError('')
    setIsEditing(true)
  }

  const handleSaveEdit = async (e) => {
    e?.preventDefault()
    if (!selectedReport) return
    if (!editTitle.trim()) {
      setEditTitleError('Enter a title for this report.')
      return
    }
    const tagsArr = editTags.split(',').map(t => t.trim()).filter(Boolean)
    const updates = {
      title: editTitle,
      description: editDesc,
      tags: tagsArr,
      scheduled: editScheduled,
      schedule_cron: editCron,
    }
    setEditSaving(true)
    setEditError('')
    const res = await updateReport(selectedReport.report_id, updates)
    setEditSaving(false)
    if (res.success) {
      setIsEditing(false)
    } else {
      setEditError(res.error ? `Could not save changes: ${res.error}. Try again.` : 'Could not save changes. Try again.')
    }
  }

  const openVersionForm = () => {
    setNewVersionContent(activeVersion.content)
    setVersionError('')
    setShowVersionForm(true)
  }

  const handleCreateVersion = async (e) => {
    e?.preventDefault()
    if (!selectedReport) return
    setVersionSaving(true)
    setVersionError('')
    const res = await createReportVersion(selectedReport.report_id, {
      content: newVersionContent,
      chart_data: activeVersion.chart_data,
      kpis: activeVersion.kpis,
      metadata: activeVersion.metadata
    })
    setVersionSaving(false)
    if (res.success) {
      setShowVersionForm(false)
      setNewVersionContent('')
      loadReportVersions(selectedReport.report_id)
    } else {
      setVersionError(res.error ? `Could not publish this version: ${res.error}. Try again.` : 'Could not publish this version. Try again.')
    }
  }

  const handleDelete = async (report) => {
    const reportId = report.report_id
    if (window.confirm(`Delete "${report.title || 'this report'}" and all its versions? This cannot be undone.`)) {
      setActionError('')
      const res = await deleteReport(reportId)
      if (res.success) {
        if (selectedReportId === reportId) {
          setSelectedReportId(null)
          setActiveVersionId(null)
        }
      } else {
        setActionError('Could not delete the report. Try again.')
      }
    }
  }

  const askAction = (
    <Button variant="primary" icon={MessageSquare} onClick={() => navigate('/app/analyze')}>Ask a question</Button>
  )

  const renderList = () => {
    if (loadError && total === 0) {
      return (
        <div className="p-4">
          <ErrorState title="Could not load reports" description={`${loadError} Check your connection and try again.`} onRetry={reload} />
        </div>
      )
    }
    if (reportsLoading && total === 0) {
      return (
        <ul className="divide-y divide-line" aria-busy="true" aria-label="Loading reports">
          {[0, 1, 2, 3].map(i => (
            <li key={i} className="space-y-2 px-4 py-4">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-1/3" />
            </li>
          ))}
        </ul>
      )
    }
    if (filtered.length === 0) {
      return (search || starredOnly) ? (
        <EmptyState
          compact
          icon={Search}
          title="No matching reports"
          description="Try a different search, or show all reports."
          action={<Button size="sm" onClick={() => { setSearch(''); setStarredOnly(false) }}>Clear filters</Button>}
        />
      ) : (
        <EmptyState
          compact
          icon={FileText}
          title="No reports yet"
          description="Ask a question about your data and turn the answer into a report. Saved reports appear here."
          action={askAction}
        />
      )
    }
    return (
      <ul className="divide-y divide-line">
        {filtered.map(report => {
          const tagsArr = tagsOf(report)
          const selected = selectedReportId === report.report_id
          const title = report.title || 'Untitled report'
          return (
            <li key={report.report_id} className={cx('flex items-start gap-2 px-3 py-3', selected && 'bg-primary-soft')}>
              <button
                type="button"
                onClick={() => selectReport(report.report_id)}
                aria-current={selected ? 'true' : undefined}
                className="focus-ring min-w-0 flex-1 rounded px-1 py-0.5 text-left"
              >
                <span className={cx('block truncate text-md font-medium', selected ? 'text-primary-text' : 'text-fg')} title={title}>{title}</span>
                <span className="mt-0.5 line-clamp-2 block break-words text-sm text-muted">{report.description || 'No description'}</span>
                <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm text-subtle">
                  {tagsArr.map(tag => <span key={tag} className="chip">{tag}</span>)}
                  <span>{formatRelativeTime(report.created_at)}</span>
                </span>
              </button>
              <div className="flex flex-shrink-0 items-center">
                <IconButton
                  icon={Star}
                  size="sm"
                  label={report.starred ? `Unstar ${title}` : `Star ${title}`}
                  tooltipSide="left"
                  aria-pressed={!!report.starred}
                  className={report.starred ? 'text-warning [&>svg]:fill-current' : undefined}
                  onClick={() => handleStar(report)}
                />
                <IconButton
                  icon={Trash2}
                  size="sm"
                  label={`Delete ${title}`}
                  tooltipSide="left"
                  className="hover:text-danger"
                  onClick={() => handleDelete(report)}
                />
              </div>
            </li>
          )
        })}
      </ul>
    )
  }

  const kpis = activeVersion?.kpis || []

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6 lg:py-8">
      <PageHeader
        title="Saved reports"
        description="Reports you have saved, with every published version. Edit the details, schedule them or publish an updated version."
        actions={<Button icon={RefreshCw} loading={reportsLoading} onClick={reload}>Refresh</Button>}
      />

      {actionError && <p className="field-error" role="alert"><AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />{actionError}</p>}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[320px_minmax(0,1fr)] lg:items-start">
        {/* Report list (hidden on small screens while a report is open) */}
        <section aria-label="Saved reports" className={cx('flex min-w-0 flex-col gap-3', selectedReport && 'hidden lg:flex')}>
          <div className="flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={ids.search} className="field-label">Search reports</label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden="true" />
                <input
                  id={ids.search}
                  type="search"
                  className="input pl-9"
                  placeholder="Title, description or tag"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
            </div>
            <IconButton
              icon={Star}
              variant="secondary"
              label={starredOnly ? 'Show all reports' : 'Show starred reports only'}
              tooltipSide="left"
              aria-pressed={starredOnly}
              className={starredOnly ? 'border-warning/40 bg-warning-soft text-warning [&>svg]:fill-current' : undefined}
              onClick={() => setStarredOnly(!starredOnly)}
            />
          </div>
          <div className="overflow-hidden rounded-lg border border-line bg-surface">{renderList()}</div>
          {total > 0 && (
            <p className="text-sm text-subtle" aria-live="polite">
              Showing {filtered.length.toLocaleString()} of {total.toLocaleString()} {total === 1 ? 'report' : 'reports'}
            </p>
          )}
        </section>

        {/* Report preview */}
        <section aria-label="Report preview" className={cx('min-w-0', !selectedReport && 'hidden lg:block')}>
          {selectedReport ? (
            <div className="flex flex-col gap-4">
              <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={() => selectReport(null)} className="self-start lg:hidden">
                All reports
              </Button>

              <article className="card overflow-hidden">
                <header className="flex flex-col gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
                  <div className="min-w-0">
                    <h2 className="break-words text-xl font-semibold text-fg">{selectedReport.title}</h2>
                    {selectedReport.description && <p className="mt-1 break-words text-base text-muted">{selectedReport.description}</p>}
                    <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-subtle">
                      <Badge tone="primary" className="tabular">Version {activeVersion.version || selectedReport.version}</Badge>
                      <span>Created {formatRelativeTime(activeVersion.created_at).toLowerCase()}</span>
                      {selectedReport.scheduled && (
                        <Badge tone="info"><CalendarClock className="h-3 w-3" aria-hidden="true" />Scheduled</Badge>
                      )}
                    </p>
                  </div>
                  <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
                    <Button size="sm" icon={Pencil} onClick={handleEditClick}>Edit details</Button>
                    <Button size="sm" variant="primary" icon={Plus} onClick={openVersionForm}>New version</Button>
                    <IconButton icon={Trash2} size="sm" label={`Delete ${selectedReport.title || 'report'}`} className="hover:text-danger" onClick={() => handleDelete(selectedReport)} />
                  </div>
                </header>

                <div className="grid grid-cols-1 md:grid-cols-[176px_minmax(0,1fr)]">
                  {/* Versions */}
                  <nav aria-label="Report versions" className="border-b border-line p-4 md:border-b-0 md:border-r">
                    {reportVersionsLoading ? (
                      <div className="space-y-2" aria-busy="true" aria-label="Loading versions">
                        <Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" />
                      </div>
                    ) : reportVersions.length === 0 ? (
                      <p className="text-sm text-muted">No earlier versions.</p>
                    ) : (
                      <>
                        <div className="md:hidden">
                          <label htmlFor={ids.versionSelect} className="field-label">Version</label>
                          <select
                            id={ids.versionSelect}
                            className="input"
                            value={activeVersion.report_id}
                            onChange={e => setActiveVersionId(e.target.value)}
                          >
                            {!reportVersions.some(v => v.report_id === selectedReport.report_id) && (
                              <option value={selectedReport.report_id}>Version {selectedReport.version} (latest)</option>
                            )}
                            {reportVersions.map(v => (
                              <option key={v.report_id} value={v.report_id}>Version {v.version} · {formatRelativeTime(v.created_at)}</option>
                            ))}
                          </select>
                        </div>
                        <div className="hidden md:block">
                          <h3 className="mb-2 text-sm font-medium text-muted">Versions</h3>
                          <ul className="space-y-1">
                            {reportVersions.map(v => {
                              const current = activeVersion.report_id === v.report_id
                              return (
                                <li key={v.report_id}>
                                  <button
                                    type="button"
                                    onClick={() => setActiveVersionId(v.report_id)}
                                    aria-current={current ? 'true' : undefined}
                                    className={cx(
                                      'focus-ring flex h-9 w-full items-center justify-between gap-2 rounded-md px-2.5 text-sm',
                                      current ? 'bg-primary-soft font-medium text-primary-text' : 'text-muted hover:bg-surface-muted hover:text-fg',
                                    )}
                                  >
                                    <span className="tabular">Version {v.version}</span>
                                    <span className="truncate text-xs text-subtle">{formatRelativeTime(v.created_at)}</span>
                                  </button>
                                </li>
                              )
                            })}
                          </ul>
                        </div>
                      </>
                    )}
                  </nav>

                  {/* Report body */}
                  <div className="min-w-0 space-y-6 p-4 sm:p-6">
                    <div className="prose-dp break-words">
                      <ReactMarkdown>{activeVersion.content || ''}</ReactMarkdown>
                    </div>

                    {activeVersion.metadata?.chart_url && (
                      <figure className="space-y-2 border-t border-line pt-5">
                        <figcaption className="text-sm font-medium text-muted">Chart</figcaption>
                        <div className="flex justify-center rounded-lg border border-line bg-surface-muted p-3">
                          <img
                            src={getBackendUrl(activeVersion.metadata.chart_url)}
                            alt={`Chart for ${selectedReport.title || 'this report'}`}
                            className="max-h-[320px] max-w-full rounded object-contain"
                          />
                        </div>
                      </figure>
                    )}

                    {kpis.length > 0 && (
                      <div className="space-y-2 border-t border-line pt-5">
                        <h3 className="text-sm font-medium text-muted">Key metrics</h3>
                        <div className="overflow-x-auto rounded-lg border border-line">
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th scope="col">Metric</th>
                                <th scope="col" className="is-number">Value</th>
                                <th scope="col">Severity</th>
                              </tr>
                            </thead>
                            <tbody>
                              {kpis.map((kpi, idx) => (
                                <tr key={idx}>
                                  <td className="font-sans">{kpi.title}</td>
                                  <td className="is-number tabular">{kpi.metric}</td>
                                  <td className="font-sans">
                                    {kpi.severity ? <Badge tone={SEVERITY_TONE[String(kpi.severity).toLowerCase()] || 'neutral'}>{kpi.severity}</Badge> : '—'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            </div>
          ) : (
            <div className="card">
              <EmptyState
                icon={FileText}
                title={total > 0 ? 'Select a report' : 'Nothing to preview yet'}
                description={total > 0 ? 'Choose a report from the list to read it and see its versions.' : 'Saved reports open here.'}
              />
            </div>
          )}
        </section>
      </div>

      {/* Edit details */}
      <Dialog
        open={isEditing && !!selectedReport}
        onClose={() => setIsEditing(false)}
        title="Edit report details"
        footer={(
          <>
            <Button onClick={() => setIsEditing(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="edit-report-form" loading={editSaving}>Save changes</Button>
          </>
        )}
      >
        <form id="edit-report-form" onSubmit={handleSaveEdit} className="flex flex-col gap-4" noValidate>
          <div>
            <label htmlFor={ids.title} className="field-label">Title</label>
            <input
              id={ids.title}
              data-autofocus
              type="text"
              className="input"
              value={editTitle}
              onChange={e => { setEditTitle(e.target.value); if (editTitleError) setEditTitleError('') }}
              aria-invalid={editTitleError ? true : undefined}
              aria-describedby={editTitleError ? ids.titleErr : undefined}
            />
            {editTitleError && (
              <p id={ids.titleErr} className="field-error" role="alert">
                <AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />{editTitleError}
              </p>
            )}
          </div>
          <div>
            <label htmlFor={ids.desc} className="field-label">Description</label>
            <textarea id={ids.desc} className="input min-h-[88px] resize-y" value={editDesc} onChange={e => setEditDesc(e.target.value)} placeholder="What this report covers and who it is for" />
          </div>
          <div>
            <label htmlFor={ids.tags} className="field-label">Tags</label>
            <input id={ids.tags} type="text" className="input" value={editTags} onChange={e => setEditTags(e.target.value)} placeholder="finance, monthly" aria-describedby={ids.tagsHint} />
            <p id={ids.tagsHint} className="field-hint">Separate tags with commas.</p>
          </div>
          <div className="flex items-start gap-2.5">
            <input
              id={ids.scheduled}
              type="checkbox"
              checked={editScheduled}
              onChange={e => setEditScheduled(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-line-strong accent-primary"
            />
            <label htmlFor={ids.scheduled} className="text-base text-fg">
              Run this report on a schedule
            </label>
          </div>
          {editScheduled && (
            <div>
              <label htmlFor={ids.cron} className="field-label">Schedule (cron pattern)</label>
              <input
                id={ids.cron}
                type="text"
                className="input font-mono"
                value={editCron}
                onChange={e => setEditCron(e.target.value)}
                placeholder="0 9 * * 1"
                aria-describedby={ids.cronHint}
              />
              <p id={ids.cronHint} className="field-hint">For example, “0 9 * * 1” runs every Monday at 9:00.</p>
            </div>
          )}
          {editError && (
            <p className="field-error" role="alert"><AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />{editError}</p>
          )}
        </form>
      </Dialog>

      {/* New version */}
      <Dialog
        open={showVersionForm && !!selectedReport}
        onClose={() => setShowVersionForm(false)}
        size="lg"
        title="Publish a new version"
        description="Edit the report text below. Earlier versions stay available."
        footer={(
          <>
            <Button onClick={() => setShowVersionForm(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="new-report-version-form" loading={versionSaving}>
              {versionSaving ? 'Publishing…' : 'Publish version'}
            </Button>
          </>
        )}
      >
        <form id="new-report-version-form" onSubmit={handleCreateVersion} className="flex flex-col gap-2" noValidate>
          <label htmlFor={ids.content} className="field-label">Report text</label>
          <textarea
            id={ids.content}
            data-autofocus
            className="input min-h-[280px] resize-y font-mono text-sm leading-relaxed"
            value={newVersionContent}
            onChange={e => setNewVersionContent(e.target.value)}
            aria-describedby={ids.contentHint}
          />
          <p id={ids.contentHint} className="field-hint">Formatting uses Markdown: # for headings, - for bullet points, **bold** for emphasis.</p>
          {versionError && (
            <p className="field-error" role="alert"><AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />{versionError}</p>
          )}
        </form>
      </Dialog>
    </div>
  )
}
