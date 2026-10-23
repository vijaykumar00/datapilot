/**
 * Helpers shared by the workspace views (insights, report builder,
 * presentation and templates).
 */
import { Suspense } from 'react'
import { apiUrl } from '../../lib/apiConfig'
import { Skeleton } from '../ui'

/** Ask the app shell to open the upload dialog. */
export const openUpload = () => window.dispatchEvent(new Event('dp:open-upload'))

/** Resolve a backend-relative asset path (e.g. a rendered report chart). */
export const getBackendUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return apiUrl(path)
}

/** Strip the "…analysis:" prefix the assistant puts in front of chart replies. */
export const chartCaption = (content, max) => {
  const text = (content || '').replace(/^.*?analysis:\s*/i, '').trim()
  if (!max || text.length <= max) return text
  return `${text.slice(0, max).trimEnd()}…`
}

/** Standard outer wrapper: scrolls inside the shell's main area. */
export function ViewPage({ children, className = '' }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={`mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6 lg:py-8 ${className}`}>
        {children}
      </div>
    </div>
  )
}

/**
 * Renders a chart spec with the lazily loaded ChartRenderer that App passes
 * down (keeps Plotly out of the marketing bundle).
 */
export function LazyChart({ ChartRenderer, spec, className = 'h-72 w-full' }) {
  if (!ChartRenderer) return null
  return (
    <Suspense fallback={<Skeleton className={className} />}>
      <ChartRenderer spec={spec} />
    </Suspense>
  )
}

/** Labelled native select used in view toolbars. */
export function SelectField({ id, label, value, onChange, children, className = '' }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="field-label">{label}</label>
      <select id={id} className="input h-10 min-w-0" value={value} onChange={onChange}>
        {children}
      </select>
    </div>
  )
}

/** Segmented control: role="tablist" with role="tab" buttons. */
export function Segmented({ label, options, value, onChange, className = '', fill = false }) {
  return (
    <div className={`max-w-full overflow-x-auto ${className}`}>
      <div
        role="tablist"
        aria-label={label}
        className={`inline-flex rounded-md border border-line bg-surface-muted p-0.5 ${fill ? 'w-full' : ''}`}
      >
        {options.map((opt) => {
          const active = opt.id === value
          const Icon = opt.icon
          return (
            <button
              key={opt.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(opt.id)}
              className={`flex h-9 flex-shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded px-3 text-sm font-medium focus-ring ${
                fill ? 'flex-1' : ''
              } ${active ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg'}`}
            >
              {Icon && <Icon className="h-4 w-4" aria-hidden="true" />}
              {opt.label}
              {opt.count !== undefined && (
                <span className="tabular rounded bg-surface-muted px-1.5 text-xs text-subtle">{opt.count}</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
