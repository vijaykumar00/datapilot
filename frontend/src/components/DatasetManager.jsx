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

  const [activeTab, setActiveTab] = useState('active') // 'active' | 'archived'
  const [search, setSearch] = useState('')
  const [editingDatasetId, setEditingDatasetId] = useState(null)
  
  // Edit form state
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editTags, setEditTags] = useState('')

  // Load all datasets (active and archived) on mount
  useEffect(() => {
    loadDatasets({ archived: 'all' })
  }, [])

  const handleEditClick = (dataset) => {
    setEditingDatasetId(dataset.dataset_id)
    setEditName(dataset.display_name || dataset.filename)
    setEditDesc(dataset.description || '')
    
    let tagsVal = ''
    if (Array.isArray(dataset.tags)) {
      tagsVal = dataset.tags.join(', ')
    } else if (typeof dataset.tags === 'string') {
      try {
        tagsVal = JSON.parse(dataset.tags || '[]').join(', ')
      } catch (_) {
        tagsVal = dataset.tags || ''
      }
    }
    setEditTags(tagsVal)
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
      loadDatasets({ archived: 'all' })
    }
  }

  const handleArchiveToggle = async (dataset) => {
    if (dataset.archived) {
      await restoreDataset(dataset.dataset_id)
    } else {
      await archiveDataset(dataset.dataset_id)
    }
    loadDatasets({ archived: 'all' })
  }

  const handleDelete = async (id) => {
    if (confirm('Permanently delete this dataset? This action deletes the file off the disk and database registry.')) {
      await deleteDataset(id)
      loadDatasets({ archived: 'all' })
    }
  }

  // Calculate statistics from the full dataset list
  const activeDatasets = datasetsList.filter(d => !d.archived)
  const archivedDatasets = datasetsList.filter(d => d.archived)

  const totalActiveCount = activeDatasets.length
  const totalRows = activeDatasets.reduce((sum, d) => sum + (d.row_count || 0), 0)
  const totalBytes = activeDatasets.reduce((sum, d) => sum + (d.file_size_bytes || 0), 0)
  const totalArchivedCount = archivedDatasets.length

  // Filter datasets currently displayed based on current tab and search query
  const displayedDatasets = (activeTab === 'active' ? activeDatasets : archivedDatasets).filter(d => {
    const term = search.toLowerCase()
    const nameMatch = (d.display_name || d.filename || '').toLowerCase().includes(term)
    const descMatch = (d.description || '').toLowerCase().includes(term)
    
    let tagsArr = []
    if (Array.isArray(d.tags)) {
      tagsArr = d.tags
    } else if (typeof d.tags === 'string') {
      try {
        tagsArr = JSON.parse(d.tags || '[]')
      } catch (_) {
        tagsArr = []
      }
    }
    const tagsMatch = tagsArr.some(t => t.toLowerCase().includes(term))
    
    return nameMatch || descMatch || tagsMatch
  })

  return (
    <div className="h-full flex flex-col bg-[#030712] animate-fade-in">
      {/* Header Toolbar */}
      <div className="px-6 py-4 border-b border-white/5 bg-[#070b14]/40 flex-shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2">
            📦 Enterprise Dataset Registry
          </h2>
          <p className="text-[10px] text-slate-500 mt-0.5">
            Manage metadata, description tags, and archiving for all multi-sheet business datasets.
          </p>
        </div>
        <button
          onClick={() => loadDatasets({ archived: 'all' })}
          className="text-[10px] font-bold text-slate-400 hover:text-slate-200 bg-white/5 border border-white/5 hover:border-brand-500/20 px-3 py-1.5 rounded-xl transition-all flex items-center gap-1.5"
        >
          <span>↻</span> Refresh Dashboard
        </button>
      </div>

      {/* Stats Cards Section */}
      <div className="px-6 pt-5 grid grid-cols-2 lg:grid-cols-4 gap-4 flex-shrink-0">
        {/* Card 1 */}
        <div className="glass p-4 rounded-2xl border border-white/5 bg-white/[0.01] hover:border-brand-500/20 transition-all flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-500/10 border border-brand-500/25 flex items-center justify-center text-lg select-none">
            📊
          </div>
          <div>
            <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider block">Active Datasets</span>
            <span className="text-lg font-extrabold text-slate-200 font-mono leading-none">{totalActiveCount}</span>
          </div>
        </div>

        {/* Card 2 */}
        <div className="glass p-4 rounded-2xl border border-white/5 bg-white/[0.01] hover:border-brand-500/20 transition-all flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/25 flex items-center justify-center text-lg select-none">
            🔢
          </div>
          <div>
            <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider block">Total Rows Analyzed</span>
            <span className="text-lg font-extrabold text-slate-200 font-mono leading-none">{totalRows.toLocaleString()}</span>
          </div>
        </div>

        {/* Card 3 */}
        <div className="glass p-4 rounded-2xl border border-white/5 bg-white/[0.01] hover:border-brand-500/20 transition-all flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center text-lg select-none">
            💾
          </div>
          <div>
            <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider block">Storage Footprint</span>
            <span className="text-lg font-extrabold text-slate-200 font-mono leading-none">{formatBytes(totalBytes)}</span>
          </div>
        </div>

        {/* Card 4 */}
        <div className="glass p-4 rounded-2xl border border-white/5 bg-white/[0.01] hover:border-brand-500/20 transition-all flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-center text-lg select-none">
            📦
          </div>
          <div>
            <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider block">Archived datasets</span>
            <span className="text-lg font-extrabold text-slate-200 font-mono leading-none">{totalArchivedCount}</span>
          </div>
        </div>
      </div>

      {/* Sub-navigation & Search Toolbar */}
      <div className="px-6 pt-5 pb-1 flex flex-col sm:flex-row gap-3 items-center justify-between flex-shrink-0">
        {/* Tab Controls */}
        <div className="flex gap-1 bg-white/[0.02] border border-white/5 p-1 rounded-xl w-full sm:w-auto">
          <button
            onClick={() => setActiveTab('active')}
            className={`flex-1 sm:flex-initial px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
              activeTab === 'active'
                ? 'bg-brand-500/10 border border-brand-500/25 text-brand-300'
                : 'text-slate-400 hover:text-slate-200 border border-transparent'
            }`}
          >
            📂 Active Datasets ({totalActiveCount})
          </button>
          <button
            onClick={() => setActiveTab('archived')}
            className={`flex-1 sm:flex-initial px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
              activeTab === 'archived'
                ? 'bg-amber-500/10 border border-amber-500/25 text-amber-400'
                : 'text-slate-400 hover:text-slate-200 border border-transparent'
            }`}
          >
            🗑️ Archived ({totalArchivedCount})
          </button>
        </div>

        {/* Search Input */}
        <div className="relative w-full sm:w-72">
          <input
            type="text"
            placeholder="Search datasets name, descriptions, or tags..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-[#050811] border border-white/5 rounded-xl px-3.5 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/40 transition-all"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2.5 top-2 text-slate-600 hover:text-slate-400 text-xs"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Dataset List */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 custom-scrollbar min-h-0">
        {datasetsLoading && datasetsList.length === 0 ? (
          <div className="text-center py-12 text-slate-500 text-xs">Loading dataset records...</div>
        ) : displayedDatasets.length === 0 ? (
          <div className="text-center py-16 text-slate-600 text-xs italic flex flex-col items-center gap-2">
            <span className="text-3xl">📦</span>
            <span>No datasets found matching selection</span>
          </div>
        ) : (
          displayedDatasets.map(dataset => {
            const isEditing = editingDatasetId === dataset.dataset_id
            const isActive = activeFileId === dataset.dataset_id
            
            let tagsArr = []
            if (Array.isArray(dataset.tags)) {
              tagsArr = dataset.tags
            } else if (typeof dataset.tags === 'string') {
              try {
                tagsArr = JSON.parse(dataset.tags || '[]')
              } catch (_) {
                tagsArr = []
              }
            }

            return (
              <div
                key={dataset.dataset_id}
                className={`glass p-5 rounded-2xl border flex flex-col gap-4 relative group transition-all duration-300 hover:border-brand-500/20 ${
                  isActive ? 'border-brand-500/25 bg-brand-500/[0.01]' : 'border-white/5'
                }`}
              >
                {/* Active check indicator */}
                {isActive && (
                  <div className="absolute top-5 right-5 bg-brand-500/10 text-brand-400 border border-brand-500/25 font-mono font-bold text-[8px] px-2 py-0.5 rounded uppercase tracking-wider select-none animate-pulse">
                    active
                  </div>
                )}

                {/* Edit Form */}
                {isEditing ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Display Name</label>
                        <input
                          type="text"
                          value={editName}
                          onChange={e => setEditName(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500/30 transition-all"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Tags (comma-separated)</label>
                        <input
                          type="text"
                          value={editTags}
                          onChange={e => setEditTags(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500/30 transition-all"
                        />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Description</label>
                      <input
                        type="text"
                        value={editDesc}
                        onChange={e => setEditDesc(e.target.value)}
                        className="w-full bg-[#050811] border border-white/5 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500/30 transition-all"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setEditingDatasetId(null)}
                        className="px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-xl text-xs text-slate-400 transition-colors font-bold"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleSave(dataset.dataset_id)}
                        className="px-3 py-1.5 bg-brand-600 hover:bg-brand-500 rounded-xl text-xs text-white transition-colors font-bold"
                      >
                        Save Settings
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Standard Display */
                  <div className="space-y-4">
                    <div className="flex items-start gap-3.5">
                      <div className="text-3xl mt-0.5 filter drop-shadow">📄</div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                          {dataset.display_name || dataset.filename}
                        </h3>
                        <p className="text-[9px] text-slate-500 font-mono mt-0.5 truncate">{dataset.filename}</p>
                        {dataset.description ? (
                          <p className="text-[11px] text-slate-400 mt-2 font-medium leading-relaxed">{dataset.description}</p>
                        ) : (
                          <p className="text-[10px] text-slate-600 mt-2 italic">No description provided. Click 'Rename' to add description details.</p>
                        )}
                      </div>
                    </div>

                    {/* Metadata Grid (6 indicators as requested) */}
                    <div className="grid grid-cols-2 md:grid-cols-6 gap-3 border-t border-b border-white/[0.03] py-3 mt-1 select-none">
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Data Rows</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.row_count?.toLocaleString() || 0}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Columns</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.column_count || 0}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Sheets</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.sheet_count || 1}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">File Size</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {formatBytes(dataset.file_size_bytes)}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Uploaded</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {formatRelativeTime(dataset.upload_date)}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Last Query</span>
                        <span className="text-xs font-bold text-slate-300 font-mono mt-0.5">
                          {dataset.last_query_date ? formatRelativeTime(dataset.last_query_date) : 'Never'}
                        </span>
                      </div>
                    </div>

                    {/* Tags and Actions Toolbar */}
                    <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                      <div className="flex flex-wrap gap-1.5">
                        {tagsArr.length > 0 ? (
                          tagsArr.map(tag => (
                            <span
                              key={tag}
                              className="bg-white/5 border border-white/5 px-2 py-0.5 rounded-lg text-[9px] font-bold text-slate-400 tracking-wide select-none"
                            >
                              #{tag}
                            </span>
                          ))
                        ) : (
                          <span className="text-[9px] text-slate-600 italic select-none">No tags</span>
                        )}
                      </div>

                      {/* Actions Buttons */}
                      <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        {!dataset.archived && !isActive && (
                          <button
                            onClick={() => setActiveFileId(dataset.dataset_id)}
                            className="px-2.5 py-1.5 bg-brand-500/10 hover:bg-brand-500/20 text-brand-400 border border-brand-500/20 rounded-xl text-[10px] font-bold transition-all"
                          >
                            Set Active
                          </button>
                        )}
                        <button
                          onClick={() => handleEditClick(dataset)}
                          className="px-2.5 py-1.5 bg-white/5 hover:bg-white/10 text-slate-300 border border-white/5 rounded-xl text-[10px] font-bold transition-all"
                        >
                          Rename / Edit
                        </button>
                        <button
                          onClick={() => handleArchiveToggle(dataset)}
                          className={`px-2.5 py-1.5 border rounded-xl text-[10px] font-bold transition-all ${
                            dataset.archived
                              ? 'bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border-emerald-500/20'
                              : 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border-amber-500/20'
                          }`}
                        >
                          {dataset.archived ? 'Restore' : 'Archive'}
                        </button>
                        <button
                          onClick={() => handleDelete(dataset.dataset_id)}
                          className="px-2.5 py-1.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 rounded-xl text-[10px] font-bold transition-all"
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
