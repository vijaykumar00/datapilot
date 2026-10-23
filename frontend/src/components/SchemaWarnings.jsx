import { useState } from 'react'
import { AlertOctagon, AlertTriangle, ChevronDown, Info, X } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { cx } from './ui'

const SEVERITY = {
  critical: { icon: AlertOctagon, tone: 'text-danger', label: 'Critical' },
  warning: { icon: AlertTriangle, tone: 'text-warning', label: 'Warning' },
  info: { icon: Info, tone: 'text-info', label: 'Note' },
}

function WarningRow({ warning, onDismiss }) {
  const cfg = SEVERITY[warning.severity] || SEVERITY.warning
  const Icon = cfg.icon
  const suggestions = warning.suggestions || []
  return (
    <li className="flex items-start gap-3 py-2.5">
      <Icon className={cx('mt-0.5 h-4 w-4 flex-shrink-0', cfg.tone)} aria-label={cfg.label} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-fg">
          {warning.title}
          {warning.affected_column && <span className="ml-2 badge badge-neutral font-mono">{warning.affected_column}</span>}
        </p>
        <p className="mt-0.5 text-sm text-muted">{warning.message}</p>
        {suggestions.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-muted marker:text-subtle">
            {suggestions.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(warning.code + (warning.affected_column || ''))}
        className="btn-ghost btn-sm btn-icon"
        aria-label={`Dismiss: ${warning.title}`}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </li>
  )
}

/**
 * One-line data quality notice shown above the conversation after an upload.
 * Expands to the full list; never covers the messages.
 */
export default function SchemaWarnings() {
  const { schemaWarnings, dismissSchemaWarning } = useDataPilot()
  const [hidden, setHidden] = useState(false)
  const [open, setOpen] = useState(false)

  if (!schemaWarnings?.length || hidden) return null

  const critical = schemaWarnings.filter((w) => w.severity === 'critical').length
  const Icon = critical ? AlertOctagon : AlertTriangle
  const tone = critical ? 'text-danger' : 'text-warning'
  const count = schemaWarnings.length

  return (
    <div id="schema-warnings-panel" className="flex-shrink-0 border-b border-line bg-surface px-3 sm:px-4">
      <div className="mx-auto flex w-full max-w-3xl items-center gap-2 py-1.5">
        <Icon className={cx('h-4 w-4 flex-shrink-0', tone)} aria-hidden="true" />
        <p className="min-w-0 flex-1 truncate text-sm text-fg">
          {count} data {count === 1 ? 'issue' : 'issues'} found{critical ? ` (${critical} critical)` : ''} — answers may be affected.
        </p>
        <button type="button" className="btn-ghost btn-sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Hide' : 'Review'} <ChevronDown className={cx('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} aria-hidden="true" />
        </button>
        <button type="button" className="btn-ghost btn-sm btn-icon" onClick={() => setHidden(true)} aria-label="Hide data issues notice">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {open && (
        <ul className="mx-auto max-h-[40vh] w-full max-w-3xl divide-y divide-line overflow-y-auto border-t border-line animate-fade-in">
          {schemaWarnings.map((w, i) => (
            <WarningRow key={`${w.code}-${w.affected_column || i}`} warning={w} onDismiss={dismissSchemaWarning} />
          ))}
        </ul>
      )}
    </div>
  )
}
