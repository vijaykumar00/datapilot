import { useState } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'

// PDF and Word uploads list the tables found in the document instead of sheets.
const MAX_CHIPS = 6

export default function SheetSelector({ file, variant = 'chips' }) {
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
  const noun = file?.metadata?.document_type ? 'Table' : 'Sheet'
  const errorText = error && (
    <p role="alert" className="field-error mt-1 flex items-start gap-1 text-xs">
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <span>Couldn't switch {noun.toLowerCase()}s: {error}</span>
    </p>
  )

  if (variant === 'select' || sheets.length > MAX_CHIPS) {
    const selectId = `sheet-select-${file.file_id}`
    return (
      <div className={variant === 'select' ? 'flex w-full min-w-0 items-center gap-2 sm:w-auto' : 'mt-1 min-w-0 px-1'}>
        <label htmlFor={selectId} className={variant === 'select' ? 'text-sm text-muted' : 'mb-1 block text-xs text-subtle'}>
          {noun} <span className="text-subtle">({sheets.length})</span>
        </label>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <select
            id={selectId}
            className="input h-9 min-w-0 flex-1 sm:w-64 sm:flex-none"
            value={pendingSheet || activeSheet || ''}
            disabled={loading}
            aria-busy={loading || undefined}
            onChange={(e) => handleSwitch(e.target.value)}
          >
            {sheets.map((sheet) => <option key={sheet} value={sheet}>{sheet}</option>)}
          </select>
          {loading && <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-primary-text" aria-label="Loading" />}
        </div>
        {errorText}
      </div>
    )
  }

  return (
    <div className="mt-1 min-w-0 px-1">
      <p id={labelId} className="mb-1 text-xs text-subtle">{noun}</p>
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
      {errorText}
    </div>
  )
}
