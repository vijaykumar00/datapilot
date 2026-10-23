import { useEffect, useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Archive, ArchiveRestore, Database, FileSpreadsheet, FileText, MessageSquare, Pencil, Search, Trash2, Upload } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { Badge, Button, EmptyState, IconButton, PageHeader, Skeleton, cx } from './ui'
import Dialog from './ui/Dialog'

function formatBytes(bytes) {
  if (!bytes) return '—'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

function parseDate(iso) {
  if (!iso) return null
  const d = new Date(iso + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? '' : 'Z'))
  return Number.isNaN(d.getTime()) ? null : d
}

function formatRelativeTime(iso) {
  const d = parseDate(iso)
  if (!d) return '—'
  const mins = Math.floor((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days} d ago`
  return d.toLocaleDateString()
}

function tagsOf(d) {
  if (Array.isArray(d.tags)) return d.tags
  if (typeof d.tags === 'string' && d.tags) {
    try { const v = JSON.parse(d.tags); return Array.isArray(v) ? v : [] } catch { return d.tags.split(',').map((t) => t.trim()).filter(Boolean) }
  }
  return []
}

const nameOf = (d) => d.display_name || d.filename || 'Untitled dataset'

function EditDatasetDialog({ dataset, onClose, onSave }) {
  const ids = { name: useId(), tags: useId(), desc: useId() }
  const [name, setName] = useState(nameOf(dataset))
  const [tags, setTags] = useState(tagsOf(dataset).join(', '))
  const [desc, setDesc] = useState(dataset.description || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { setError('Enter a name for this dataset.'); return }
    setSaving(true)
    setError('')
    const res = await onSave({ display_name: name.trim(), description: desc, tags: tags.split(',').map((t) => t.trim()).filter(Boolean) })
    setSaving(false)
    if (res?.success === false) setError(res.error || 'Could not save changes. Try again.')
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Edit dataset details"
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="edit-dataset-form" loading={saving}>Save changes</Button>
        </>
      )}
    >
      <form id="edit-dataset-form" onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <div>
          <label htmlFor={ids.name} className="field-label">Name</label>
          <input id={ids.name} className="input" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error && !name.trim()} aria-describedby={error ? `${ids.name}-err` : undefined} />
        </div>
        <div>
          <label htmlFor={ids.tags} className="field-label">Tags</label>
          <input id={ids.tags} className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="finance, q3" aria-describedby={`${ids.tags}-hint`} />
          <p id={`${ids.tags}-hint`} className="field-hint">Separate tags with commas.</p>
        </div>
        <div>
          <label htmlFor={ids.desc} className="field-label">Description</label>
          <textarea id={ids.desc} className="input min-h-[88px] resize-y" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What this data contains and where it came from" />
        </div>
        {error && <p id={`${ids.name}-err`} className="field-error" role="alert">{error}</p>}
      </form>
    </Dialog>
  )
}

function Stat({ label, value }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-surface px-4 py-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="tabular mt-0.5 truncate text-xl font-semibold text-fg">{value}</dd>
    </div>
  )
}

export default function DatasetManager() {
  const navigate = useNavigate()
  const {
    datasetsList, datasetsLoading, loadDatasets, updateDataset, archiveDataset, restoreDataset, deleteDataset,
    activeFileId, setActiveFileId, files, activeFileIds, toggleFileActive,
  } = useDataPilot()

  const [tab, setTab] = useState('active')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [actionError, setActionError] = useState('')
  const searchId = useId()

  useEffect(() => {
    loadDatasets({ archived: 'all' })
  }, [])

  const reload = () => loadDatasets({ archived: 'all' })
  const all = datasetsList || []
  const active = all.filter((d) => !d.archived)
  const archived = all.filter((d) => d.archived)

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase()
    const list = tab === 'active' ? active : archived
    if (!term) return list
    return list.filter((d) => nameOf(d).toLowerCase().includes(term)
      || (d.description || '').toLowerCase().includes(term)
      || tagsOf(d).some((t) => String(t).toLowerCase().includes(term)))
  }, [search, tab, active, archived])

  const run = async (id, fn, failMsg) => {
    setBusyId(id)
    setActionError('')
    try {
      const res = await fn()
      if (res && res.success === false) setActionError(res.error || failMsg)
      await reload()
    } catch {
      setActionError(failMsg)
    } finally {
      setBusyId(null)
    }
  }

  const ask = (d) => {
    setActiveFileId(d.dataset_id)
    if ((files || []).some((f) => f.file_id === d.dataset_id) && !(activeFileIds || []).includes(d.dataset_id)) toggleFileActive(d.dataset_id)
    navigate('/app/analyze')
  }

  const onDelete = (d) => {
    if (!window.confirm(`Permanently delete "${nameOf(d)}"? The file and its data will be removed. This cannot be undone.`)) return
    run(d.dataset_id, () => deleteDataset(d.dataset_id), 'Could not delete the dataset. Try again.')
  }

  const openUpload = () => window.dispatchEvent(new CustomEvent('dp:open-upload'))
  const totalRows = active.reduce((s, d) => s + (d.row_count || 0), 0)
  const totalBytes = active.reduce((s, d) => s + (d.file_size_bytes || 0), 0)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6 lg:py-8">
      <PageHeader
        title="Datasets"
        description="Every spreadsheet you have uploaded. Pick one to ask questions about it."
        actions={<Button variant="primary" icon={Upload} onClick={openUpload}>Upload data</Button>}
      />

      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Datasets" value={active.length.toLocaleString()} />
        <Stat label="Total rows" value={totalRows.toLocaleString()} />
        <Stat label="Storage used" value={formatBytes(totalBytes)} />
        <Stat label="Archived" value={archived.length.toLocaleString()} />
      </dl>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div role="tablist" aria-label="Dataset status" className="inline-flex w-full rounded-md border border-line bg-surface-muted p-0.5 sm:w-auto">
          {[['active', 'Active', active.length], ['archived', 'Archived', archived.length]].map(([key, label, n]) => (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cx('flex h-9 flex-1 items-center justify-center gap-1.5 rounded px-4 text-base font-medium sm:flex-none',
                tab === key ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg')}
            >
              {label} <span className="tabular text-subtle">{n}</span>
            </button>
          ))}
        </div>
        <div className="relative w-full sm:w-72">
          <label htmlFor={searchId} className="sr-only">Search datasets</label>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden="true" />
          <input id={searchId} type="search" className="input pl-9" placeholder="Search by name, tag or description" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {actionError && <p className="field-error" role="alert">{actionError}</p>}

      <section aria-label={tab === 'active' ? 'Active datasets' : 'Archived datasets'} className="overflow-hidden rounded-lg border border-line bg-surface">
        {datasetsLoading && all.length === 0 ? (
          <ul className="divide-y divide-line" aria-busy="true" aria-label="Loading datasets">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex items-center gap-3 px-4 py-4">
                <Skeleton className="h-9 w-9 rounded-md" />
                <div className="flex-1 space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-3 w-1/2" /></div>
              </li>
            ))}
          </ul>
        ) : shown.length === 0 ? (
          search ? (
            <EmptyState icon={Search} title="No matching datasets" description={`Nothing matches “${search}”. Try a different name or tag.`} action={<Button onClick={() => setSearch('')}>Clear search</Button>} />
          ) : tab === 'archived' ? (
            <EmptyState icon={Archive} title="No archived datasets" description="Datasets you archive are kept here and can be restored at any time." />
          ) : (
            <EmptyState icon={Database} title="No datasets yet" description="Upload a CSV or Excel file to start asking questions about it." action={<Button variant="primary" icon={Upload} onClick={openUpload}>Upload data</Button>} />
          )
        ) : (
          <>
            <div className="hidden grid-cols-[minmax(0,1fr)_90px_80px_90px_110px_176px] gap-3 border-b border-line bg-surface-muted px-4 py-2 text-sm font-medium text-muted lg:grid" aria-hidden="true">
              <span>Name</span><span className="text-right">Rows</span><span className="text-right">Columns</span><span className="text-right">Size</span><span>Uploaded</span><span className="text-right">Actions</span>
            </div>
            <ul className="divide-y divide-line">
              {shown.map((d) => {
                const ext = (d.filename || '').split('.').pop().toLowerCase()
                const Icon = ext === 'csv' ? FileText : FileSpreadsheet
                const isCurrent = activeFileId === d.dataset_id
                const busy = busyId === d.dataset_id
                const tags = tagsOf(d)
                return (
                  <li key={d.dataset_id} className={cx('flex flex-col gap-3 px-4 py-3 lg:grid lg:grid-cols-[minmax(0,1fr)_90px_80px_90px_110px_176px] lg:items-center lg:gap-3', busy && 'opacity-60')} aria-busy={busy || undefined}>
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-surface-muted text-muted"><Icon className="h-[18px] w-[18px]" aria-hidden="true" /></span>
                      <div className="min-w-0 flex-1">
                        <p className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className="truncate text-md font-medium text-fg" title={nameOf(d)}>{nameOf(d)}</span>
                          {isCurrent && <Badge tone="primary">In use</Badge>}
                          <Badge>{ext.toUpperCase() || 'FILE'}</Badge>
                        </p>
                        {d.description && <p className="mt-0.5 line-clamp-2 text-sm text-muted">{d.description}</p>}
                        {tags.length > 0 && (
                          <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="Tags">
                            {tags.map((t) => <li key={t} className="chip">{t}</li>)}
                          </ul>
                        )}
                        <p className="mt-1 text-sm text-subtle lg:hidden">
                          {[d.row_count != null && `${d.row_count.toLocaleString()} rows`, d.column_count != null && `${d.column_count} columns`, formatBytes(d.file_size_bytes), `uploaded ${formatRelativeTime(d.upload_date).toLowerCase()}`].filter(Boolean).join(' · ')}
                        </p>
                        {d.last_query_date && <p className="mt-0.5 text-sm text-subtle">Last asked about {formatRelativeTime(d.last_query_date).toLowerCase()}</p>}
                      </div>
                    </div>
                    <span className="tabular hidden text-right text-base text-fg lg:block">{d.row_count?.toLocaleString() ?? '—'}</span>
                    <span className="tabular hidden text-right text-base text-fg lg:block">{d.column_count ?? '—'}</span>
                    <span className="tabular hidden text-right text-base text-fg lg:block">{formatBytes(d.file_size_bytes)}</span>
                    <span className="hidden text-base text-muted lg:block">{formatRelativeTime(d.upload_date)}</span>
                    <div className="flex items-center gap-1 lg:justify-end">
                      {!d.archived && (
                        <Button size="sm" variant="secondary" icon={MessageSquare} onClick={() => ask(d)} className="mr-auto lg:mr-0">Ask</Button>
                      )}
                      {!d.archived && <IconButton icon={Pencil} label={`Edit ${nameOf(d)}`} tooltipSide="top" onClick={() => setEditing(d)} disabled={busy} />}
                      <IconButton
                        icon={d.archived ? ArchiveRestore : Archive}
                        label={d.archived ? `Restore ${nameOf(d)}` : `Archive ${nameOf(d)}`}
                        tooltipSide="top"
                        disabled={busy}
                        onClick={() => run(d.dataset_id, () => (d.archived ? restoreDataset(d.dataset_id) : archiveDataset(d.dataset_id)), 'Could not update the dataset. Try again.')}
                      />
                      <IconButton icon={Trash2} label={`Delete ${nameOf(d)}`} tooltipSide="top" className="hover:text-danger" disabled={busy} onClick={() => onDelete(d)} />
                    </div>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </section>

      {editing && (
        <EditDatasetDialog
          dataset={editing}
          onClose={() => setEditing(null)}
          onSave={async (patch) => {
            const res = await updateDataset(editing.dataset_id, patch)
            if (res?.success !== false) { setEditing(null); reload() }
            return res
          }}
        />
      )}
    </div>
  )
}
