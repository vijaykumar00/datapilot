import { useState } from 'react'
import { AlertOctagon, AlertTriangle, ChevronDown, Info, RotateCcw, XCircle } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { Button, cx } from './ui'

const SEVERITY = {
  critical: { icon: AlertOctagon, tone: 'text-danger', box: 'border-danger/30 bg-danger-soft', label: 'Critical' },
  error: { icon: XCircle, tone: 'text-danger', box: 'border-danger/30 bg-danger-soft', label: 'Error' },
  warning: { icon: AlertTriangle, tone: 'text-warning', box: 'border-warning/30 bg-warning-soft', label: 'Warning' },
  info: { icon: Info, tone: 'text-info', box: 'border-info/30 bg-info-soft', label: 'Note' },
}

/**
 * Explains a failed answer in plain language: what went wrong, how to fix it,
 * and (when the server offers one) a one-click recovery.
 */
export default function ErrorIntelligencePanel({ intelligentError, fallbackMessage }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const { switchSheet, retryLastMessage } = useDataPilot()
  const [recovering, setRecovering] = useState(false)
  const [recoveryError, setRecoveryError] = useState(null)

  if (!intelligentError) {
    return (
      <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-3 text-base text-fg">
        <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden="true" />
        <span className="min-w-0 break-words">{fallbackMessage || 'Something went wrong. Please try again.'}</span>
      </div>
    )
  }

  const sev = SEVERITY[intelligentError.severity] || SEVERITY.error
  const Icon = sev.icon
  const suggestions = intelligentError.suggestions || []
  const details = intelligentError.details || []
  const hasRows = intelligentError.affected_rows?.[0] != null
  // Provider switching is a server setting in the MVP, so only sheet recovery is offered here.
  const recovery = intelligentError.recovery?.type === 'switch_sheet' ? intelligentError.recovery : null

  const handleRecovery = async () => {
    if (recovering) return
    setRecovering(true)
    setRecoveryError(null)
    try {
      const res = await switchSheet(recovery.file_id, recovery.sheet)
      if (!res.success) throw new Error(res.error || 'Could not switch sheet')
      await retryLastMessage()
    } catch (err) {
      setRecoveryError(err.message)
    } finally {
      setRecovering(false)
    }
  }

  return (
    <div role="alert" className={cx('overflow-hidden rounded-lg border', sev.box)}>
      <div className="flex items-start gap-2.5 px-3.5 py-3">
        <Icon className={cx('mt-0.5 h-4 w-4 flex-shrink-0', sev.tone)} aria-label={sev.label} />
        <div className="min-w-0 flex-1">
          <p className="text-base font-semibold text-fg">{intelligentError.title}</p>
          <p className="mt-0.5 break-words text-base text-fg">{intelligentError.message}</p>
          {(intelligentError.affected_column || hasRows) && (
            <p className="mt-1.5 flex flex-wrap gap-1.5">
              {intelligentError.affected_column && <span className="badge badge-neutral font-mono">{intelligentError.affected_column}</span>}
              {hasRows && <span className="badge badge-neutral">Rows {intelligentError.affected_rows[0]}–{intelligentError.affected_rows[1]}</span>}
            </p>
          )}
          {suggestions.length > 0 && (
            <div className="mt-2.5">
              <p className="text-sm font-medium text-muted">Try this</p>
              <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-base text-fg marker:text-subtle">
                {suggestions.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            </div>
          )}
          {recovery && (
            <div className="mt-3">
              <Button size="sm" variant="primary" icon={RotateCcw} loading={recovering} onClick={handleRecovery}>
                {recovery.label || 'Fix and try again'}
              </Button>
              {recoveryError && <p className="field-error mt-1.5">That didn't work: {recoveryError}</p>}
            </div>
          )}
        </div>
      </div>
      {details.length > 0 && (
        <div className="border-t border-line/60">
          <button type="button" onClick={() => setDetailsOpen((v) => !v)} aria-expanded={detailsOpen}
            className="flex w-full items-center justify-between px-3.5 py-2 text-sm text-muted hover:text-fg focus-ring">
            Technical details{intelligentError.code ? ` (${intelligentError.code})` : ''}
            <ChevronDown className={cx('h-4 w-4 transition-transform', detailsOpen && 'rotate-180')} aria-hidden="true" />
          </button>
          {detailsOpen && (
            <div className="space-y-1 px-3.5 pb-3">
              {details.map((d, i) => <p key={i} className="break-words font-mono text-xs text-muted">{d}</p>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
