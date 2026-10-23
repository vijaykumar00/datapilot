import { useState } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'

export default function SheetSelector({ file }) {
  const { switchSheet } = useDataPilot()
  const sheets = file?.metadata?.sheet_names || []
  const activeSheet = file?.metadata?.active_sheet

  const [loading, setLoading] = useState(false)
  const [pendingSheet, setPendingSheet] = useState(null)
  const [error, setError] = useState(null)

  if (sheets.length <= 1) return null

  const handleSwitch = async (sheet) => {
    if (sheet === activeSheet || loading) return
    setLoading(true)
    setPendingSheet(sheet)
    setError(null)
    const result = await switchSheet(file.file_id, sheet)
    setLoading(false)
    setPendingSheet(null)
    if (!result.success) setError(result.error)
  }

  const labelId = `sheet-selector-label-${file.file_id}`

  return (
    <div className="mt-1 min-w-0 px-1">
      <p id={labelId} className="mb-1 text-xs text-subtle">Sheet</p>
      <div role="group" aria-labelledby={labelId} className="flex min-w-0 flex-wrap gap-1">
        {sheets.map(sheet => {
          const active = sheet === activeSheet
          const pending = loading && sheet === pendingSheet
          return (
            <button
              key={sheet}
              type="button"
              onClick={() => handleSwitch(sheet)}
              disabled={loading}
              aria-pressed={active}
              aria-busy={pending || undefined}
              title={sheet}
              className={`focus-ring inline-flex max-w-full items-center gap-1 rounded border px-2 py-1 text-xs transition-colors disabled:cursor-wait disabled:opacity-60 ${
                active
                  ? 'border-primary/40 bg-primary-soft font-medium text-primary-text'
                  : 'border-line bg-surface text-muted hover:border-line-strong hover:text-fg'
              }`}
            >
              {pending && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
              <span className="truncate">{sheet}</span>
            </button>
          )
        })}
      </div>
      {error && (
        <p role="alert" className="field-error mt-1 flex items-start gap-1 text-xs">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          <span>Couldn't switch sheets: {error}</span>
        </p>
      )}
    </div>
  )
}
