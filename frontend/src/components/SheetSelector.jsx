import { useState } from 'react'
import { useDataPilot } from '../hooks/useDataPilot'

export default function SheetSelector({ file }) {
  const { switchSheet } = useDataPilot()
  const sheets = file?.metadata?.sheet_names || []
  const activeSheet = file?.metadata?.active_sheet

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  if (sheets.length <= 1) return null

  const handleSwitch = async (sheet) => {
    if (sheet === activeSheet || loading) return
    setLoading(true)
    setError(null)
    const result = await switchSheet(file.file_id, sheet)
    setLoading(false)
    if (!result.success) setError(result.error)
  }

  return (
    <div className="mt-1 px-1">
      <p className="text-[10px] text-slate-500 mb-1 uppercase tracking-wider">Sheet</p>
      <div className="flex flex-wrap gap-1">
        {sheets.map(sheet => (
          <button
            key={sheet}
            onClick={() => handleSwitch(sheet)}
            disabled={loading}
            className={`text-[10px] px-2 py-0.5 rounded border transition-all ${
              sheet === activeSheet
                ? 'bg-brand-500/20 border-brand-500/50 text-brand-300'
                : 'border-white/10 text-slate-400 hover:border-brand-500/30 hover:text-slate-200'
            } ${loading ? 'opacity-50 cursor-wait' : ''}`}
          >
            {loading && sheet === activeSheet ? '⏳' : ''}{sheet}
          </button>
        ))}
      </div>
      {error && (
        <p className="text-[10px] text-rose-400 mt-1">{error}</p>
      )}
    </div>
  )
}
