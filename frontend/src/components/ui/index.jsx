/**
 * DataPilot UI primitives.  Small, dependency-free building blocks that every
 * page uses so buttons, badges, empty states and skeletons look the same
 * everywhere.  Icons come from lucide-react only.
 */
import { forwardRef } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'

const cx = (...parts) => parts.filter(Boolean).join(' ')
export { cx }

const VARIANT = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-destructive',
}
const SIZE = { sm: 'btn-sm', md: '', lg: 'btn-lg' }

/** Button with optional leading icon and a loading state that keeps its width. */
export const Button = forwardRef(function Button(
  { variant = 'secondary', size = 'md', icon: Icon, loading = false, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(VARIANT[variant], SIZE[size], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : Icon ? <Icon className="h-4 w-4" aria-hidden="true" /> : null}
      {children}
    </button>
  )
})

/** Icon-only button: always has an accessible name and a tooltip. */
export const IconButton = forwardRef(function IconButton(
  { icon: Icon, label, variant = 'ghost', size = 'md', className, tooltip = true, tooltipSide = 'bottom', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      data-tooltip={tooltip ? label : undefined}
      data-tooltip-side={tooltip ? tooltipSide : undefined}
      className={cx(VARIANT[variant], SIZE[size], 'btn-icon', className)}
      {...rest}
    >
      <Icon className={size === 'sm' ? 'h-4 w-4' : 'h-[18px] w-[18px]'} aria-hidden="true" />
    </button>
  )
})

export function Badge({ tone = 'neutral', className, children, ...rest }) {
  return <span className={cx('badge', `badge-${tone}`, className)} {...rest}>{children}</span>
}

export function Spinner({ className, label = 'Loading' }) {
  return <Loader2 className={cx('h-4 w-4 animate-spin text-subtle', className)} role="status" aria-label={label} />
}

/** Placeholder block for content whose shape is known. */
export function Skeleton({ className, ...rest }) {
  return <div className={cx('skeleton', className)} aria-hidden="true" {...rest} />
}

/** Page heading row: title, optional description, actions on the right. */
export function PageHeader({ title, description, actions, children, className }) {
  return (
    <header className={cx('flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-base text-muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Empty state: says what is missing and offers the next step. */
export function EmptyState({ icon: Icon, title, description, action, className, compact = false }) {
  return (
    <div className={cx('flex flex-col items-center justify-center text-center', compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-14', className)}>
      {Icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-surface-muted text-muted">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      )}
      <div className="max-w-sm">
        <p className="text-md font-semibold text-fg">{title}</p>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  )
}

/** Inline error with a retry action. */
export function ErrorState({ title = 'Something went wrong', description, onRetry, className }) {
  return (
    <div role="alert" className={cx('flex items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4', className)}>
      <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-danger" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-base font-semibold text-fg">{title}</p>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {onRetry && <Button size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

/** Section card with an optional header row. */
export function Card({ title, description, actions, className, bodyClassName, children, as: Tag = 'section' }) {
  return (
    <Tag className={cx('card', className)}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div className="min-w-0">
            {title && <h2 className="text-md font-semibold text-fg">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cx('p-4 sm:p-5', bodyClassName)}>{children}</div>
    </Tag>
  )
}
