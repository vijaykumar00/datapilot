import { useCallback, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { AlertCircle, CheckCircle2, Eye, FileSpreadsheet, FileText, Loader2, Pencil, Trash2, UploadCloud } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import SheetSelector from './SheetSelector'
import { cx } from './ui'

const MAX_MB = 50

function formatSize(kb) {
  if (!kb && kb !== 0) return null
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(kb))} KB`
}

function FileRow({ file, onRemove, onPreview, isActive, onToggle }) {
  const { renameFile } = useDataPilot()
  const ext = file.filename.split('.').pop().toLowerCase()
  const Icon = ext === 'csv' ? FileText : FileSpreadsheet
  const [editing, setEditing] = useState(false)
  const [renameVal, setRenameVal] = useState(file.filename)
  const inputRef = useRef(null)

  const commitRename = async () => {
    setEditing(false)
    const trimmed = renameVal.trim()
    if (trimmed && trimmed !== file.filename) await renameFile(file.file_id, trimmed)
  }

  const meta = [
    file.row_count != null ? `${file.row_count.toLocaleString()} rows` : null,
    file.column_count != null ? `${file.column_count} columns` : null,
    formatSize(file.file_size_kb),
  ].filter(Boolean).join(' · ')

  return (
    <li className="flex flex-col gap-1">
      <div className={cx('group flex items-center gap-3 rounded-md border px-3 py-2', isActive ? 'border-primary/40 bg-primary-soft/50' : 'border-line bg-surface')}>
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            className="h-4 w-4 flex-shrink-0 accent-[rgb(var(--c-primary))]"
            checked={isActive}
            onChange={onToggle}
            aria-label={`Use ${file.filename} in analysis`}
          />
          <Icon className="h-5 w-5 flex-shrink-0 text-subtle" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {editing ? (
              <input
                ref={inputRef}
                value={renameVal}
                onChange={(e) => setRenameVal(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setEditing(false) }}
                onClick={(e) => e.preventDefault()}
                className="input py-1"
                aria-label="File name"
                autoFocus
              />
            ) : (
              <span className="block truncate text-base font-medium text-fg" title={file.filename}>{file.filename}</span>
            )}
            <span className="block truncate text-xs text-subtle">{meta}</span>
          </span>
        </label>
        <div className="flex flex-shrink-0 items-center gap-0.5">
          <button type="button" className="btn-ghost btn-sm btn-icon" data-tooltip="Rename" aria-label={`Rename ${file.filename}`}
            onClick={() => { setRenameVal(file.filename); setEditing(true); setTimeout(() => inputRef.current?.select(), 10) }}>
            <Pencil className="h-4 w-4" aria-hidden="true" />
          </button>
          <button type="button" id={`preview-${file.file_id}`} className="btn-ghost btn-sm btn-icon" data-tooltip="Preview" aria-label={`Preview ${file.filename}`}
            onClick={() => onPreview(file.file_id)}>
            <Eye className="h-4 w-4" aria-hidden="true" />
          </button>
          <button type="button" id={`remove-${file.file_id}`} className="btn-ghost btn-sm btn-icon hover:text-danger" data-tooltip="Remove" aria-label={`Remove ${file.filename}`}
            onClick={() => { if (window.confirm(`Remove "${file.filename}" from this workspace?`)) onRemove(file.file_id) }}>
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <SheetSelector file={file} />
    </li>
  )
}

/**
 * Drag-and-drop uploader with a per-file status list.  Uploads keep going if
 * the surrounding dialog closes; large files are processed by a background job.
 */
export default function FileUploader({ showFiles = true }) {
  const { files, activeFileIds, uploadFile, removeFile, toggleFileActive, setPreviewFile } = useDataPilot()
  const [queue, setQueue] = useState([]) // {name, status: 'uploading'|'done'|'error', message}

  const onDrop = useCallback(async (accepted, rejected) => {
    const rejectedItems = (rejected || []).map((r) => ({
      name: r.file.name, status: 'error', message: 'Only CSV, XLSX and XLS files can be uploaded.',
    }))
    setQueue((q) => [...rejectedItems, ...q.filter((i) => i.status === 'uploading')])
    for (const file of accepted) {
      if (file.size > MAX_MB * 1024 * 1024) {
        setQueue((q) => [{ name: file.name, status: 'error', message: `This file is larger than ${MAX_MB} MB.` }, ...q])
        continue
      }
      setQueue((q) => [{ name: file.name, status: 'uploading' }, ...q.filter((i) => i.name !== file.name)])
      const result = await uploadFile(file)
      setQueue((q) => q.map((i) => (i.name === file.name
        ? (result?.success
          ? { name: file.name, status: 'done', message: 'Ready to analyze.' }
          : { name: file.name, status: 'error', message: result?.error || 'Upload failed. Please try again.' })
        : i)))
    }
  }, [uploadFile])

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    noClick: true,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    multiple: true,
  })

  const busy = queue.some((i) => i.status === 'uploading')

  return (
    <div className="flex flex-col gap-4">
      <div {...getRootProps()} className={cx('drop-zone', isDragActive && 'drag-over')} id="file-drop-zone">
        <input {...getInputProps()} id="file-input" aria-label="Choose spreadsheet files" />
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-soft text-primary-text">
            <UploadCloud className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <p className="text-md font-medium text-fg">{isDragActive ? 'Drop to upload' : 'Drag spreadsheets here'}</p>
            <p className="mt-0.5 text-sm text-muted">CSV, XLSX or XLS · up to {MAX_MB} MB each</p>
          </div>
          <button type="button" className="btn-secondary" onClick={open}>
            Choose files
          </button>
        </div>
      </div>

      {queue.length > 0 && (
        <ul className="flex flex-col gap-2" aria-live="polite">
          {queue.map((item) => (
            <li key={item.name} className={cx(
              'flex items-start gap-2.5 rounded-md border px-3 py-2 text-sm',
              item.status === 'error' ? 'border-danger/30 bg-danger-soft' : item.status === 'done' ? 'border-success/30 bg-success-soft' : 'border-line bg-surface-muted',
            )}>
              {item.status === 'uploading' && <Loader2 className="mt-0.5 h-4 w-4 flex-shrink-0 animate-spin text-primary-text" aria-hidden="true" />}
              {item.status === 'done' && <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-success" aria-hidden="true" />}
              {item.status === 'error' && <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden="true" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-fg">{item.name}</span>
                <span className="block text-muted">
                  {item.status === 'uploading' ? 'Uploading and reading columns. Large files can take a minute.' : item.message}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {busy && <span className="sr-only">Upload in progress</span>}

      {showFiles && files.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium text-fg">
            In this workspace <span className="font-normal text-subtle">· checked files are used when you ask questions</span>
          </p>
          <ul className="flex flex-col gap-1.5">
            {files.map((file) => (
              <FileRow
                key={file.file_id}
                file={file}
                isActive={activeFileIds.includes(file.file_id)}
                onToggle={() => toggleFileActive(file.file_id)}
                onRemove={removeFile}
                onPreview={setPreviewFile}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
