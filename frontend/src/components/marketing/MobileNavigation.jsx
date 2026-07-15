import { useEffect, useRef } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { marketingNavItems } from '../../data/marketing'

export default function MobileNavigation({ open, onClose, triggerRef }) {
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusableSelector =
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    const focusable = () => Array.from(panelRef.current?.querySelectorAll(focusableSelector) || [])

    const focusTimer = window.setTimeout(() => {
      focusable()[0]?.focus()
    }, 0)

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose()
        triggerRef.current?.focus()
      }

      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.clearTimeout(focusTimer)
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose, open, triggerRef])

  if (!open) return null

  return (
    <div className="mobile-nav-shell md:hidden" role="presentation" onMouseDown={onClose}>
      <nav
        id="mobile-navigation"
        ref={panelRef}
        className="mobile-nav-panel"
        aria-label="Mobile navigation"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border-default)] pb-4">
          <span className="text-sm font-semibold text-[var(--text-primary)]">Menu</span>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close navigation">
            <span aria-hidden="true">x</span>
          </button>
        </div>

        <div className="mt-4 grid gap-2">
          {marketingNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={onClose}
              className={({ isActive }) => `marketing-mobile-link ${isActive ? 'is-active' : ''}`}
              end={item.path === '/'}
            >
              {item.label}
            </NavLink>
          ))}
        </div>

        <div className="mt-5 grid gap-3 border-t border-[var(--border-default)] pt-5">
          <Link to="/login" onClick={onClose} className="btn-ghost justify-center">
            Sign In
          </Link>
          <Link to="/signup" onClick={onClose} className="btn-primary justify-center">
            Try Free
          </Link>
        </div>
      </nav>
    </div>
  )
}
