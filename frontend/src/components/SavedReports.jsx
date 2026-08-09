import { useState, useEffect, useMemo } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'
import ReactMarkdown from 'react-markdown'
import { apiUrl } from '../lib/apiConfig'

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

const getBackendUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return apiUrl(path)
}

export default function SavedReports() {
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
  
  // Edit forms
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editScheduled, setEditScheduled] = useState(false)
  const [editCron, setEditCron] = useState('')

  // New version form
  const [newVersionContent, setNewVersionContent] = useState('')
  const [showVersionForm, setShowVersionForm] = useState(false)
  const [versionSaving, setVersionSaving] = useState(false)

  useEffect(() => {
    loadReports()
  }, [])

  const selectedReport = useMemo(() => {
    return reports.find(r => r.report_id === selectedReportId) || null
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
          !r.title.toLowerCase().includes(q) &&
          !r.description.toLowerCase().includes(q) &&
          !(r.tags || '').toLowerCase().includes(q)
        ) return false
      }
      return true
    })
  }, [reports, search, starredOnly])

  const handleStar = async (report) => {
    await updateReport(report.report_id, { starred: !report.starred })
  }

  const handleEditClick = () => {
    if (!selectedReport) return
    setEditTitle(selectedReport.title)
    setEditDesc(selectedReport.description)
    setEditTags(Array.isArray(selectedReport.tags) ? selectedReport.tags.join(', ') : typeof selectedReport.tags === 'string' ? JSON.parse(selectedReport.tags || '[]').join(', ') : '')
    setEditScheduled(Boolean(selectedReport.scheduled))
    setEditCron(selectedReport.schedule_cron || '')
    setIsEditing(true)
  }

  const handleSaveEdit = async () => {
    if (!selectedReport) return
    const tagsArr = editTags.split(',').map(t => t.trim()).filter(Boolean)
    const updates = {
      title: editTitle,
      description: editDesc,
      tags: tagsArr,
      scheduled: editScheduled,
      schedule_cron: editCron,
    }
    const res = await updateReport(selectedReport.report_id, updates)
    if (res.success) {
      setIsEditing(false)
    }
  }

  const handleCreateVersion = async () => {
    if (!selectedReport) return
    setVersionSaving(true)
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
    }
  }

  const handleDelete = async (reportId) => {
    if (confirm('Are you sure you want to permanently delete this report and all its versions?')) {
      const res = await deleteReport(reportId)
      if (res.success) {
        if (selectedReportId === reportId) {
          setSelectedReportId(null)
          setActiveVersionId(null)
        }
      }
    }
  }

  return (
    <div className="h-full grid grid-cols-1 lg:grid-cols-[340px_1fr] overflow-hidden bg-[#030712] animate-fade-in">
      
      {/* Left List View */}
      <div className="border-r border-white/5 flex flex-col min-h-0 bg-[#070b14]/50">
        <div className="p-4 border-b border-white/5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold text-slate-200 uppercase tracking-widest flex items-center gap-1.5">
              📋 Saved Reports
            </h2>
            <button
              onClick={() => loadReports()}
              className="text-[10px] text-slate-500 hover:text-slate-200 transition-colors bg-white/5 px-2 py-0.5 rounded"
            >
              ↻ Refresh
            </button>
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Search reports..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="flex-1 bg-[#050811] border border-white/5 rounded-xl px-3 py-1.5 text-xs text-slate-200 focus:outline-none placeholder-slate-600"
            />
            <button
              onClick={() => setStarredOnly(!starredOnly)}
              className={`px-3 py-1.5 rounded-xl border text-xs transition-all ${
                starredOnly ? 'bg-amber-500/10 border-amber-500/35 text-amber-400' : 'bg-[#050811] border-white/5 text-slate-400'
              }`}
            >
              ⭐
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
          {reportsLoading ? (
            <div className="text-center py-8 text-slate-500 text-xs">Loading reports...</div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-slate-600 text-xs italic">No reports found</div>
          ) : (
            filtered.map(report => {
              const tagsArr = Array.isArray(report.tags) ? report.tags : JSON.parse(report.tags || '[]')
              return (
                <div
                  key={report.report_id}
                  onClick={() => {
                    setSelectedReportId(report.report_id)
                    setActiveVersionId(null)
                  }}
                  className={`p-3 rounded-xl border transition-all cursor-pointer relative group flex flex-col gap-1.5 ${
                    selectedReportId === report.report_id
                      ? 'bg-brand-500/10 border-brand-500/30'
                      : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.05]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-xs font-bold text-slate-200 truncate">{report.title}</h3>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleStar(report)
                        }}
                        className="text-[10px] text-slate-500 hover:text-amber-400"
                      >
                        {report.starred ? '⭐' : '☆'}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(report.report_id)
                        }}
                        className="text-[10px] text-slate-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        ✕
                      </button>
                    </div>
                  </div>

                  <p className="text-[10px] text-slate-500 line-clamp-2">{report.description || 'No description'}</p>

                  <div className="flex items-center justify-between text-[9px] text-slate-600">
                    <div className="flex gap-1">
                      {tagsArr.map(tag => (
                        <span key={tag} className="bg-white/5 px-1 py-0.5 rounded text-slate-400">#{tag}</span>
                      ))}
                    </div>
                    <span>{formatRelativeTime(report.created_at)}</span>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Right Canvas / Preview Panel */}
      <div className="flex flex-col min-h-0 bg-[#050811]/30">
        {selectedReport ? (
          <div className="flex-1 flex flex-col min-h-0">
            {/* Toolbar Header */}
            <div className="px-6 py-3 border-b border-white/5 flex items-center justify-between bg-[#0b0f19]/60 backdrop-blur-md">
              <div className="space-y-0.5">
                <h2 className="text-sm font-bold text-slate-200">{selectedReport.title}</h2>
                <p className="text-[10px] text-slate-500">
                  Version {activeVersion.version || selectedReport.version} · Created {formatRelativeTime(activeVersion.created_at)}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleEditClick}
                  className="px-3 py-1.5 bg-white/5 border border-white/5 rounded-xl text-xs font-semibold text-slate-300 hover:bg-white/10"
                >
                  ✏️ Edit Details
                </button>
                <button
                  onClick={() => {
                    setNewVersionContent(activeVersion.content)
                    setShowVersionForm(true)
                  }}
                  className="px-3 py-1.5 bg-brand-600 hover:bg-brand-500 rounded-xl text-xs font-bold text-white shadow-md shadow-brand-600/10"
                >
                  ➕ New Version
                </button>
              </div>
            </div>

            {/* Split content layout: Left version list, Right actual report */}
            <div className="flex-1 flex min-h-0">
              
              {/* Report Versions Drawer */}
              <div className="w-48 border-r border-white/5 overflow-y-auto p-3 space-y-2 bg-[#070b14]/20 custom-scrollbar">
                <h4 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider px-1">Versions</h4>
                {reportVersionsLoading ? (
                  <div className="text-[10px] text-slate-500 p-2">Loading versions...</div>
                ) : (
                  reportVersions.map(v => (
                    <div
                      key={v.report_id}
                      onClick={() => setActiveVersionId(v.report_id)}
                      className={`p-2 rounded-lg border text-[10px] cursor-pointer transition-all ${
                        activeVersion.report_id === v.report_id
                          ? 'bg-brand-500/10 border-brand-500/25 text-brand-300 font-bold'
                          : 'bg-white/[0.01] border-white/5 text-slate-400 hover:bg-white/5'
                      }`}
                    >
                      <div className="flex justify-between">
                        <span>Ver {v.version}</span>
                        <span className="text-slate-500">{formatRelativeTime(v.created_at)}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Document/Editor workspace */}
              <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
                
                {/* Edit Modal (if active) */}
                {isEditing && (
                  <div className="mb-6 p-4 rounded-xl border border-white/5 bg-[#0b0f19] space-y-4">
                    <h3 className="text-xs font-bold text-slate-200">Edit Details</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-400 uppercase tracking-wider">Title</label>
                        <input
                          type="text"
                          value={editTitle}
                          onChange={e => setEditTitle(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-lg px-2.5 py-1.5 text-xs text-slate-200"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[9px] text-slate-400 uppercase tracking-wider">Tags (comma-separated)</label>
                        <input
                          type="text"
                          value={editTags}
                          onChange={e => setEditTags(e.target.value)}
                          className="w-full bg-[#050811] border border-white/5 rounded-lg px-2.5 py-1.5 text-xs text-slate-200"
                        />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[9px] text-slate-400 uppercase tracking-wider">Description</label>
                      <textarea
                        value={editDesc}
                        onChange={e => setEditDesc(e.target.value)}
                        className="w-full bg-[#050811] border border-white/5 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 h-16 resize-none"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={editScheduled}
                          onChange={e => setEditScheduled(e.target.checked)}
                          className="rounded border-white/5 bg-[#050811]"
                        />
                        <label className="text-[10px] text-slate-300 font-semibold">Enable Schedule Execution</label>
                      </div>
                      {editScheduled && (
                        <div className="space-y-1">
                          <label className="text-[9px] text-slate-400 uppercase tracking-wider">Cron Pattern</label>
                          <input
                            type="text"
                            value={editCron}
                            onChange={e => setEditCron(e.target.value)}
                            placeholder="e.g. 0 9 * * 1"
                            className="w-full bg-[#050811] border border-white/5 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono"
                          />
                        </div>
                      )}
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setIsEditing(false)}
                        className="px-3 py-1 bg-white/5 rounded-lg text-xs text-slate-400"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveEdit}
                        className="px-3 py-1 bg-brand-600 rounded-lg text-xs text-white"
                      >
                        Save updates
                      </button>
                    </div>
                  </div>
                )}

                {/* Create Version Workspace */}
                {showVersionForm && (
                  <div className="mb-6 p-4 rounded-xl border border-white/5 bg-[#0b0f19] space-y-3">
                    <h3 className="text-xs font-bold text-slate-200">Publish New Report Version</h3>
                    <p className="text-[10px] text-slate-500">Edit the Markdown narrative text directly in this draft box to publish a new official record.</p>
                    <textarea
                      value={newVersionContent}
                      onChange={e => setNewVersionContent(e.target.value)}
                      className="w-full bg-[#050811] border border-white/5 rounded-lg px-3 py-2 text-xs text-slate-200 h-64 font-mono leading-relaxed"
                    />
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setShowVersionForm(false)}
                        className="px-3 py-1 bg-white/5 rounded-lg text-xs text-slate-400"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleCreateVersion}
                        disabled={versionSaving}
                        className="px-3 py-1 bg-brand-600 rounded-lg text-xs text-white"
                      >
                        {versionSaving ? 'Publishing...' : 'Publish Version'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Physical Document Canvas Preview */}
                <div className="max-w-[210mm] mx-auto bg-white text-slate-800 shadow-2xl p-12 border border-slate-200 rounded-sm flex flex-col justify-between font-sans leading-relaxed min-h-[297mm]">
                  <div className="space-y-6">
                    {/* Header */}
                    <div className="flex justify-between items-center border-b pb-2.5 border-slate-100">
                      <span className="font-mono text-[9px] font-bold uppercase tracking-wider text-slate-400">
                        DATAPILOT SYSTEM DOCUMENT
                      </span>
                      <span className="font-mono text-[8px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-bold uppercase">
                        Ver {activeVersion.version || selectedReport.version}
                      </span>
                    </div>

                    <div className="space-y-1">
                      <h1 className="text-lg font-black text-slate-900 leading-tight">
                        {selectedReport.title}
                      </h1>
                      <p className="text-[10px] text-slate-400 italic">
                        {selectedReport.description}
                      </p>
                    </div>

                    {/* Narrative body */}
                    <div className="prose prose-sm text-slate-700 max-w-none text-[11px] leading-relaxed font-sans space-y-3">
                      <ReactMarkdown
                        components={{
                          h1: ({node, ...props}) => <h1 className="text-[11px] font-bold text-slate-800 border-b pb-1 mt-3" {...props} />,
                          h2: ({node, ...props}) => <h2 className="text-[10px] font-bold text-slate-800 mt-2" {...props} />,
                          h3: ({node, ...props}) => <h3 className="text-[9.5px] font-semibold text-slate-700 mt-1.5" {...props} />,
                          p: ({node, ...props}) => <p className="mb-1.5 text-[10px] leading-normal" {...props} />,
                          ul: ({node, ...props}) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5" {...props} />,
                          ol: ({node, ...props}) => <ol className="list-decimal pl-4 mb-1.5 space-y-0.5" {...props} />,
                          li: ({node, ...props}) => <li className="text-[9.5px]" {...props} />,
                        }}
                      >
                        {activeVersion.content}
                      </ReactMarkdown>
                    </div>

                    {/* Embedded charts */}
                    {activeVersion.metadata?.chart_url && (
                      <div className="space-y-1.5 border-t pt-4 border-slate-100">
                        <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                          Embedded Visual Performance
                        </div>
                        <div className="p-2 border border-slate-100 rounded-xl bg-slate-50/50 flex flex-col items-center">
                          <img
                            src={getBackendUrl(activeVersion.metadata.chart_url)}
                            alt="Report Chart"
                            className="max-h-[200px] object-contain rounded"
                          />
                        </div>
                      </div>
                    )}

                    {/* Tabulated KPIs */}
                    {activeVersion.kpis && activeVersion.kpis.length > 0 && (
                      <div className="space-y-1.5 border-t pt-4 border-slate-100">
                        <div className="text-[9px] font-bold text-slate-400 uppercase tracking-wider font-mono">
                          Calculated Indicators
                        </div>
                        <div className="overflow-hidden rounded-xl border border-slate-150 shadow-sm bg-white">
                          <table className="w-full text-left text-[9.5px] border-collapse">
                            <thead>
                              <tr className="bg-slate-100 text-slate-700 text-[8.5px] font-bold uppercase font-mono tracking-wider">
                                <th className="px-3.5 py-1.5">Metric</th>
                                <th className="px-3.5 py-1.5">Value</th>
                                <th className="px-3.5 py-1.5 text-right">Severity</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {activeVersion.kpis.map((kpi, idx) => (
                                <tr key={idx}>
                                  <td className="px-3.5 py-1.5 font-medium text-slate-800">{kpi.title}</td>
                                  <td className="px-3.5 py-1.5 font-mono text-slate-700">{kpi.metric}</td>
                                  <td className="px-3.5 py-1.5 text-right font-mono text-slate-500 uppercase text-[8px]">{kpi.severity}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="border-t border-slate-100 pt-3 mt-8 flex justify-between items-center text-[8px] font-mono text-slate-400 uppercase tracking-wider">
                    <span>Generated by DataPilot report engine</span>
                    <span>Confidential report record</span>
                  </div>
                </div>

              </div>

            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500 text-xs italic">
            Select a report from the list on the left to display its canvas.
          </div>
        )}
      </div>

    </div>
  )
}
