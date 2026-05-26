import { useMemo, useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

const PAGE_SIZE = 50

export default function DataPreview() {
  const { files, previewFileId } = useDataPilot()
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(0)

  const file = files.find(f => f.file_id === previewFileId)

  if (!file) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8 gap-4">
        <div className="text-4xl">👁️</div>
        <p className="text-slate-400 text-sm">Select a file from the sidebar to preview its data</p>
      </div>
    )
  }

  const columns = file.columns || []
  const rows = file.sample_data || []

  // Filter + sort (client-side on sample data)
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

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
    setPage(0)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 flex-shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">{file.filename}</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {file.row_count?.toLocaleString()} rows · {file.column_count} columns
            {filter && ` · ${processed.length} matching`}
          </p>
        </div>
        <input
          id="preview-filter"
          type="text"
          value={filter}
          onChange={e => { setFilter(e.target.value); setPage(0) }}
          placeholder="Filter rows…"
          className="input-dark w-40 h-8 text-xs py-1.5"
        />
      </div>

      {/* Column info strip */}
      <div className="flex gap-2 px-5 py-2 overflow-x-auto border-b border-white/5 flex-shrink-0">
        {columns.slice(0, 12).map(col => (
          <div key={col.name}
            className="flex-shrink-0 glass-sm px-2 py-1 text-[10px] text-slate-400 rounded-lg">
            <span className="font-mono text-brand-400">{col.name}</span>
            <span className="text-slate-600 ml-1">({col.dtype})</span>
            {col.null_count > 0 && (
              <span className="ml-1 text-amber-500/70">·{col.null_count}✗</span>
            )}
          </div>
        ))}
        {columns.length > 12 && (
          <span className="flex-shrink-0 text-[10px] text-slate-600 self-center">
            +{columns.length - 12} more
          </span>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {pageRows.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            No rows match your filter.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-10 text-center text-slate-600">#</th>
                {columns.map(col => (
                  <th
                    key={col.name}
                    className="cursor-pointer hover:text-brand-300 select-none"
                    onClick={() => handleSort(col.name)}
                    id={`sort-${col.name}`}
                  >
                    <div className="flex items-center gap-1">
                      {col.name}
                      {sortCol === col.name && (
                        <span className="text-brand-400">{sortDir === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row, i) => (
                <tr key={page * PAGE_SIZE + i}>
                  <td className="text-center text-slate-600">{page * PAGE_SIZE + i + 1}</td>
                  {columns.map(col => {
                    const val = row[col.name]
                    const isNull = val === null || val === undefined || val === ''
                    return (
                      <td key={col.name} title={isNull ? 'null' : String(val)}>
                        {isNull
                          ? <span className="text-rose-500/50 italic text-[10px]">null</span>
                          : String(val)
                        }
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-5 py-2 border-t border-white/5 flex-shrink-0">
          <span className="text-xs text-slate-500">
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-1">
            <button
              id="prev-page-btn"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="btn-ghost text-xs px-2 py-1 disabled:opacity-30"
            >
              ← Prev
            </button>
            <button
              id="next-page-btn"
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="btn-ghost text-xs px-2 py-1 disabled:opacity-30"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
