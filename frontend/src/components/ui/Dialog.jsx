/**
 * Accessible dialog: focus moves in on open and back to the opener on close,
 * Tab is trapped inside, Escape and the backdrop close it.  On phones it
 * becomes a bottom sheet.
 */
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { IconButton, cx } from './index'

const FOCUSABLE = 'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'

export default function Dialog({ open, onClose, title, description, children, footer, size = 'md', className }) {
  const panelRef = useRef(null)
  const openerRef = useRef(null)
  const titleId = useId()
  const descId = useId()
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    openerRef.current = document.activeElement
    const t = window.setTimeout(() => {
      const first = panelRef.current?.querySelector('[data-autofocus]') || panelRef.current?.querySelector(FOCUSABLE)
      first?.focus()
    }, 20)
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onCloseRef.current?.() }
      if (e.key === 'Tab' && panelRef.current) {
        const items = [...panelRef.current.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null)
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      window.clearTimeout(t)
      document.removeEventListener('keydown', onKey, true)
      openerRef.current?.focus?.()
    }
  }, [open])

  if (!open) return null
  const width = { sm: 'sm:max-w-md', md: 'sm:max-w-lg', lg: 'sm:max-w-2xl', xl: 'sm:max-w-4xl' }[size]

  return createPortal(
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descId : undefined}
        className={cx('dialog-panel pb-safe flex flex-col', width, className)}
      >
        {title && (
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-lg font-semibold text-fg">{title}</h2>
              {description && <p id={descId} className="mt-0.5 text-sm text-muted">{description}</p>}
            </div>
            <IconButton icon={X} label="Close" size="sm" tooltip={false} onClick={onClose} className="-mr-1.5 -mt-0.5" />
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line bg-surface-muted/50 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
