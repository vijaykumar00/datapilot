import { useSearchParams } from 'react-router-dom'
import { cx } from '../ui'

/**
 * Tab strip under the top bar for pages that group related views
 * (Reports, Saved).  The selected tab lives in the URL (?view=…) so it can be
 * linked to and survives a reload.
 */
export function useSubView(views, param = 'view') {
  const [params, setParams] = useSearchParams()
  const requested = params.get(param)
  const current = views.some((v) => v.id === requested) ? requested : views[0].id
  const select = (id) => {
    const next = new URLSearchParams(params)
    next.set(param, id)
    setParams(next, { replace: true })
  }
  return [current, select]
}

export default function SubNav({ label, views, current, onSelect }) {
  return (
    <div className="flex-shrink-0 border-b border-line bg-surface px-4 sm:px-6">
      <div role="tablist" aria-label={label} className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto">
        {views.map((v) => {
          const Icon = v.icon
          const active = v.id === current
          return (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onSelect(v.id)}
              className={cx(
                'relative flex h-11 flex-shrink-0 items-center gap-2 px-3 text-base font-medium focus-ring',
                active ? 'text-fg' : 'text-muted hover:text-fg',
              )}
            >
              {Icon && <Icon className="h-4 w-4" aria-hidden="true" />}
              {v.label}
              {active && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" aria-hidden="true" />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
