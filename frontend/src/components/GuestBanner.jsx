/**
 * GuestBanner.jsx — slim notice for guest workspaces with usage on demand.
 */
import { useState } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { cx } from './ui'

function UsageBar({ label, current, limit }) {
  const pct = limit > 0 ? Math.min(100, (current / limit) * 100) : 0
  const tone = pct >= 90 ? 'bg-danger' : pct >= 70 ? 'bg-warning' : 'bg-primary'
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted">{label}</span>
        <span className="tabular font-medium text-fg">{current} of {limit}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink/10" role="progressbar" aria-label={`${label} used`} aria-valuenow={current} aria-valuemin={0} aria-valuemax={limit}>
        <div className={cx('h-full rounded-full transition-[width] duration-base', tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function GuestBanner({ onSignUp, onLogin }) {
  const { isGuest, isAuthenticated, guestUsage, guestLimits } = useAuth()
  const [expanded, setExpanded] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  if (!isGuest || isAuthenticated || dismissed) return null

  const usageItems = [
    { label: 'Uploads', key: 'upload_count' },
    { label: 'Questions', key: 'query_count' },
    { label: 'Reports', key: 'report_count' },
    { label: 'Exports', key: 'export_count' },
  ]
  const nearLimit = usageItems.some(({ key }) => {
    const limit = guestLimits?.[key] ?? 0
    return limit > 0 && (guestUsage?.[key] ?? 0) / limit >= 0.6
  })

  return (
    <div className={cx('flex-shrink-0 border-b px-3 py-2 sm:px-4', nearLimit ? 'border-warning/30 bg-warning-soft' : 'border-line bg-primary-soft/60')}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-sm text-fg">
          <span className="font-semibold">Guest workspace.</span>{' '}
          {nearLimit ? "You're close to the guest limits — create a free account to keep going." : 'Guest files and chats are temporary. Create a free account to keep them.'}
        </p>
        <div className="flex items-center gap-1.5">
          <button type="button" className="btn-ghost btn-sm" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            Usage <ChevronDown className={cx('h-3.5 w-3.5 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={onLogin}>Sign in</button>
          <button type="button" className="btn-primary btn-sm" onClick={onSignUp}>Create free account</button>
          <button type="button" className="btn-ghost btn-sm btn-icon" onClick={() => setDismissed(true)} aria-label="Hide guest notice">
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="mt-3 grid gap-4 pb-1 sm:grid-cols-2 lg:grid-cols-4">
          {usageItems.map(({ label, key }) => (
            <UsageBar key={key} label={label} current={guestUsage?.[key] ?? 0} limit={guestLimits?.[key] ?? 0} />
          ))}
        </div>
      )}
    </div>
  )
}

export default GuestBanner
