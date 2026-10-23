/**
 * UserMenu.jsx — account menu in the top bar.
 * Keyboard: Enter/Space opens, arrows move, Escape closes and returns focus.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, CreditCard, LogOut, Settings, UserPlus } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { cx } from './ui'

function UserMenu({ onSettings }) {
  const { user, logout, isAuthenticated, isGuest } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  useEffect(() => {
    if (open) window.setTimeout(() => menuRef.current?.querySelector('[role="menuitem"]')?.focus(), 10)
  }, [open])

  if (!isAuthenticated && !isGuest) return null

  const displayName = user?.full_name || user?.email?.split('@')[0] || 'Guest'
  const initials = (user?.full_name || user?.email || 'G')
    .split(/[\s@]/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || 'G'

  const close = () => { setOpen(false); buttonRef.current?.focus() }
  const onMenuKey = (e) => {
    const items = [...menuRef.current.querySelectorAll('[role="menuitem"]')]
    const i = items.indexOf(document.activeElement)
    if (e.key === 'Escape') { e.preventDefault(); close() }
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length]?.focus() }
    if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus() }
    if (e.key === 'Tab') setOpen(false)
  }
  const item = 'flex h-9 w-full items-center gap-2.5 rounded px-2.5 text-left text-base text-fg hover:bg-ink/[0.06] focus:bg-ink/[0.06] focus:outline-none'

  return (
    <div className="relative" ref={ref}>
      <button
        ref={buttonRef}
        type="button"
        className="flex h-9 items-center gap-2 rounded-md pl-1 pr-1.5 hover:bg-ink/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${displayName}`}
      >
        <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-primary-soft text-xs font-semibold text-primary-text">
          {user?.avatar_url ? <img src={user.avatar_url} alt="" className="h-full w-full object-cover" /> : initials}
        </span>
        <span className="hidden max-w-[140px] truncate text-sm font-medium text-fg sm:inline">{isGuest && !isAuthenticated ? 'Guest' : displayName}</span>
        <ChevronDown className={cx('hidden h-4 w-4 text-subtle transition-transform sm:block', open && 'rotate-180')} aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          onKeyDown={onMenuKey}
          className="absolute right-0 z-50 mt-1.5 w-64 rounded-lg border border-line bg-elevated p-1.5 shadow-float animate-pop-in"
        >
          {isAuthenticated ? (
            <>
              <div className="px-2.5 pb-2 pt-1.5">
                <p className="truncate text-base font-semibold text-fg">{user?.full_name || displayName}</p>
                <p className="truncate text-sm text-muted">{user?.email}</p>
              </div>
              <div className="my-1 h-px bg-line" />
              <button role="menuitem" type="button" className={item} onClick={() => { setOpen(false); onSettings?.() }}>
                <Settings className="h-4 w-4 text-subtle" aria-hidden="true" /> Settings
              </button>
              <button role="menuitem" type="button" className={item} onClick={() => { setOpen(false); navigate('/app/billing') }}>
                <CreditCard className="h-4 w-4 text-subtle" aria-hidden="true" /> Plan & billing
              </button>
              <div className="my-1 h-px bg-line" />
              <button role="menuitem" type="button" className={cx(item, 'text-danger')} onClick={() => { setOpen(false); logout() }}>
                <LogOut className="h-4 w-4" aria-hidden="true" /> Sign out
              </button>
            </>
          ) : (
            <>
              <div className="px-2.5 pb-2 pt-1.5">
                <p className="text-base font-semibold text-fg">You're using a guest workspace</p>
                <p className="mt-0.5 text-sm text-muted">Create a free account to keep your files and chats.</p>
              </div>
              <button role="menuitem" type="button" className={item} onClick={() => { setOpen(false); navigate('/signup') }}>
                <UserPlus className="h-4 w-4 text-subtle" aria-hidden="true" /> Create free account
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default UserMenu
