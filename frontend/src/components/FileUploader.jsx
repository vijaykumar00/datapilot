import { useCallback, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useDataPilot } from '../hooks/useDataPilot'
import SheetSelector from './SheetSelector'

const ICONS = { csv: '📄', xlsx: '📊', xls: '📊' }
const MAX_MB = 50

function FileCard({ file, onRemove, onPreview, isActive, onToggle }) {
  const { renameFile } = useDataPilot()
  const ext = file.filename.split('.').pop().toLowerCase()
  const icon = ICONS[ext] || '📁'
  const [editing, setEditing] = useState(false)
  const [renameVal, setRenameVal] = useState(file.filename)
  const inputRef = useRef(null)

  const startEdit = (e) => {
    e.stopPropagation()
    setRenameVal(file.filename)
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 10)
  }

  const commitRename = async () => {
    setEditing(false)
    const trimmed = renameVal.trim()
    if (trimmed && trimmed !== file.filename) {
      await renameFile(file.file_id, trimmed)
    }
  }

  const sizeMB = file.file_size_kb ? (file.file_size_kb / 1024).toFixed(1) : null

  return (
    <div className="flex flex-col gap-1">
      <div
        className={`file-pill ${isActive ? 'file-pill-active' : 'file-pill-inactive'} group`}
        onClick={() => { if (!editing) { onToggle(); onPreview(file.file_id) } }}
      >
        <span className="text-base">{icon}</span>
        <div className="flex-1 min-w-0">
          {editing ? (
            <input
              ref={inputRef}
              value={renameVal}
              onChange={e => setRenameVal(e.target.value)}
              onBlur={commitRename}
              onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setEditing(false) }}
              onClick={e => e.stopPropagation()}
              className="w-full bg-transparent border-b border-brand-500 text-sm text-slate-200 outline-none py-0"
              autoFocus
            />
          ) : (
            <p className="truncate font-medium text-sm" title={file.filename}>{file.filename}</p>
          )}
          <p className="text-slate-500 text-[10px] mt-0.5">
            {file.row_count?.toLocaleString()} rows · {file.column_count} cols
            {sizeMB ? ` · ${sizeMB} MB` : ''}
          </p>
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            className="p-0.5 rounded hover:text-amber-400 text-slate-500"
            onClick={startEdit}
            title="Rename file"
          >
            <PencilIcon />
          </button>
          <button
            id={`preview-${file.file_id}`}
            className="p-0.5 rounded hover:text-brand-400 text-slate-500"
            onClick={e => { e.stopPropagation(); onPreview(file.file_id) }}
            title="Preview data"
          >
            <EyeIcon />
          </button>
          <button
            id={`remove-${file.file_id}`}
            className="p-0.5 rounded hover:text-rose-400 text-slate-500"
            onClick={e => {
              e.stopPropagation()
              if (window.confirm(`Remove "${file.filename}"?`)) onRemove(file.file_id)
            }}
            title="Remove file"
          >
            <XIcon />
          </button>
        </div>
      </div>
      <SheetSelector file={file} />
    </div>
  )
}

export default function FileUploader() {
  const { files, activeFileIds, uploadFile, removeFile, toggleFileActive, setPreviewFile } = useDataPilot()
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(null)

  const onDrop = useCallback(async (accepted) => {
    if (!accepted.length) return
    setUploading(true)
    setUploadError(null)

    for (const file of accepted) {
      if (file.size > MAX_MB * 1024 * 1024) {
        setUploadError(`${file.name} exceeds ${MAX_MB}MB limit`)
        continue
      }
      setUploadProgress(`Uploading ${file.name}…`)
      const result = await uploadFile(file)
      if (!result.success) {
        setUploadError(result.error || 'Upload failed')
      }
    }
    setUploading(false)
    setUploadProgress(null)
  }, [uploadFile])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    multiple: true,
  })

  return (
    <div className="flex flex-col gap-3">
      <div
        {...getRootProps()}
        className={`drop-zone ${isDragActive ? 'drag-over' : ''}`}
        id="file-drop-zone"
      >
        <input {...getInputProps()} id="file-input" />
        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full"
              style={{ animation: 'spin 0.8s linear infinite' }} />
            <p className="text-sm text-slate-400">{uploadProgress || 'Processing…'}</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 pointer-events-none">
            <div className="text-3xl mb-1">{isDragActive ? '📂' : '☁️'}</div>
            <p className="text-sm font-medium text-slate-300">
              {isDragActive ? 'Drop to upload' : 'Drop CSV or Excel'}
            </p>
            <p className="text-xs text-slate-500">or click to browse · max {MAX_MB}MB</p>
          </div>
        )}
      </div>

      {uploadError && (
        <div className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2 animate-fade-in">
          ⚠️ {uploadError}
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold px-1">
            Loaded files
          </p>
          {files.map(file => (
            <FileCard
              key={file.file_id}
              file={file}
              isActive={activeFileIds.includes(file.file_id)}
              onToggle={() => toggleFileActive(file.file_id)}
              onRemove={removeFile}
              onPreview={setPreviewFile}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function PencilIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
    </svg>
  )
}

function EyeIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  )
}

function XIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  )
}
