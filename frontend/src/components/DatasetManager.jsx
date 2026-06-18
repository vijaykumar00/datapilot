import { useState, useEffect } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

function formatBytes(bytes) {
  if (!bytes) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatRelativeTime(iso) {
  if (!iso) return ''
  try {
    const diff = Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}d ago`
    return new Date(iso).toLocaleDateString()
  } catch {
    return ''
  }
}

export default function DatasetManager() {
  const {
    datasetsList,
    datasetsLoading,
    loadDatasets,
    updateDataset,
    archiveDataset,
    restoreDataset,
    deleteDataset,
    activeFileId,
    setActiveFileId,
  } = useDataPilot()

  const [showArchived, setShowArchived] = useState(false)
  const [editingDatasetId, setEditingDatasetId] = useState(null)
  
  // Edit form state
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editTags, setEditTags] = useState('')

  useEffect(() => {
    loadDatasets({ archived: showArchived })
  }, [showArchived])

  const handleEditClick = (dataset) => {
    setEditingDatasetId(dataset.dataset_id)
    setEditName(dataset.display_name || dataset.filename)
    setEditDesc(dataset.description || '')
    setEditTags(Array.isArray(dataset.tags) ? dataset.tags.join(', ') : typeof dataset.tags === 'string' ? JSON.parse(dataset.tags || '[]').join(', ') : '')
  }

  const handleSave = async (id) => {
    const tagsArr = editTags.split(',').map(t => t.trim()).filter(Boolean)
    const res = await updateDataset(id, {
      display_name: editName,
      description: editDesc,
      tags: tagsArr
    })
    if (res.success) {
      setEditingDatasetId(null)
      loadDatasets({ archived: showArchived })
    }
  }

  const handleArchiveToggle = async (dataset) => {
    if (dataset.archived) {
      await restoreDataset(dataset.dataset_id)
    } else {
      await archiveDataset(dataset.dataset_id)
    }
    loadDatasets({ archived: showArchived })
  }

  const handleDelete = async (id) => {
    if (confirm('Permanently delete this dataset? This action deletes the file off the disk and database registry.')) {
      await deleteDataset(id)
      loadDatasets({ archived: showArchived })
    }
  }

  return (
    <div className="h-full flex flex-col bg-[#030712] animate-fade-in">
      {/* Header toolbar */}
      <div className="px-6 py-4 border-b border-white/5 bg-[#070b14]/40 flex-shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-200">📦 Dataset Registry Manager</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">Profile, register, archive, or edit local files and sheets</p>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setShowArchived(!showArchived)}
            className={`px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all ${
              showArchived ? 'bg-amber-500/10 border-amber-500/35 text-amber-400' : 'bg-white/5 border-white/5 text-slate-400'
            }`}
          >
            📂 Show Archived
          </button>
          <button
            onClick={() => loadDatasets({ archived: showArchived })}
            className="text-xs text-slate-400 hover:text-slate-200 bg-white/5 border border-white/5 px-3 py-1.5 rounded-xl transition-all"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Dataset Grid List */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 custom-scrollbar min-h-0">
        {datasetsLoading ? (
          <div className="text-center py-12 text-slate-500 text-xs">Loading dataset records...</div>
        ) : datasetsList.length === 0 ? (
          <div className="text-center py-16 text-slate-600 text-xs italic flex flex-col items-center gap-2">
            <span className="text-3xl">📦</span>
            <span>No registered datasets found</span>
          </div>
        ) : (
          datasetsList.map(dataset => {
            const isEditing = editingDatasetId === dataset.dataset_id
            const tagsArr = Array.isArray(dataset.tags) ? dataset.tags : JSON.parse(dataset.tags || '[]')
            const isActive = activeFileId === dataset.dataset_id

            return (
              <div
                key={dataset.dataset_id}
                className={`glass p-4.5 rounded-2xl border flex flex-col gap-4 relative group transition-all duration-300 hover:border-brand-500/25 ${
                  isActive ? 'border-brand-500/35 bg-brand-500/[0.01]' : 'border-white/5'
                }`}
              >
                {/* Active check indicator */}
                {isActive && (
                  <div className="absolute top-4.5 right-4.5 bg-brand-500 text-white font-mono font-bold text-[8px] px-1.5 py-0.5 rounded uppercase tracking-wider">
                    active
                  </div>
                )}

                {/* Edit Form */}
                {isEditing ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-500 uppercase tracking-wider">Display Name</label>
                        <input
                          type="text"
                          value={editName}
                          onChange={e => setEditName(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-200"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-500 uppercase tracking-wider">Tags (comma-separated)</label>
                        <input
                          type="text"
                          value={editTags}
                          onChange={e => setEditTags(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-200"
                        />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-slate-500 uppercase tracking-wider">Description</label>
                      <input
                        type="text"
                        value={editDesc}
                        onChange={e => setEditDesc(e.target.value)}
                        className="w-full bg-[#050811] border border-white/5 rounded-xl px-2.5 py-1.5 text-xs text-slate-200"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setEditingDatasetId(null)}
                        className="px-2.5 py-1 bg-white/5 rounded-lg text-xs text-slate-400"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSave(dataset.dataset_id)}
                        className="px-2.5 py-1 bg-brand-600 rounded-lg text-xs text-white"
                      >
                        Save
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Standard Display */
                  <div className="space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="text-2xl mt-0.5">📄</div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-xs font-bold text-slate-200">{dataset.display_name || dataset.filename}</h3>
                        <p className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">{dataset.filename}</p>
                        {dataset.description && (
                          <p className="text-[11px] text-slate-400 mt-1">{dataset.description}</p>
                        )}
                      </div>
                    </div>

                    {/* Metadata indicators */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 border-t border-b border-white/[0.03] py-2.5">
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase">Data Rows</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.row_count?.toLocaleString() || 0}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase">Columns</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.column_count || 0}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase">File Size</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {formatBytes(dataset.file_size_bytes)}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase">Uploaded</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {formatRelativeTime(dataset.upload_date)}
                        </span>
                      </div>
                    </div>

                    {/* Tags and actions toolbar */}
                    <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                      <div className="flex gap-1">
                        {tagsArr.map(tag => (
                          <span key={tag} className="bg-white/5 border border-white/5 px-1.5 py-0.5 rounded text-[9px] text-slate-400">
                            #{tag}
                          </span>
                        ))}
                      </div>

                      <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        {!dataset.archived && !isActive && (
                          <button
                            onClick={() => setActiveFileId(dataset.dataset_id)}
                            className="px-2 py-1 bg-brand-500/10 hover:bg-brand-500/20 text-brand-400 border border-brand-500/20 rounded-lg text-[10px] font-bold"
                          >
                            Set Active
                          </button>
                        )}
                        <button
                          onClick={() => handleEditClick(dataset)}
                          className="px-2 py-1 bg-white/5 hover:bg-white/10 text-slate-300 border border-white/5 rounded-lg text-[10px] font-bold"
                        >
                          Rename
                        </button>
                        <button
                          onClick={() => handleArchiveToggle(dataset)}
                          className={`px-2 py-1 border rounded-lg text-[10px] font-bold ${
                            dataset.archived
                              ? 'bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border-emerald-500/20'
                              : 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border-amber-500/20'
                          }`}
                        >
                          {dataset.archived ? 'Restore' : 'Archive'}
                        </button>
                        <button
                          onClick={() => handleDelete(dataset.dataset_id)}
                          className="px-2 py-1 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 rounded-lg text-[10px] font-bold"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
