/**
 * AppShell — the authenticated workspace frame.
 *
 * Desktop: collapsible sidebar (full or icon-only) + top bar + content.
 * Mobile (< 1024px): top bar with a menu button; navigation opens as a drawer.
 * The content area is the only scroll container, so pages never fight the frame.
 */
import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ChevronsLeft, ChevronsRight, Menu, Search, Upload, X } from 'lucide-react'
import { ThemeToggle } from './ThemeToggle'
import { FOOTER_ITEMS, NAV_GROUPS, pageTitle } from './navigation'
import { LogoMark, Wordmark } from '../ui/Logo'
import { IconButton, cx } from '../ui'
import { useAuth } from '../../contexts/AuthContext'
import { useDataPilot } from '../../hooks/useDataPilot'
import UserMenu from '../UserMenu'
import GuestBanner from '../GuestBanner'
import CommandPalette from '../CommandPalette'
import AuthModal from '../AuthModal'
import GuestChoiceDialog, { guestChoiceMade } from '../GuestChoiceDialog'
import { SAMPLE_QUESTIONS } from '../../lib/sampleData'
import ToastContainer from '../ToastContainer'
import UploadDialog from './UploadDialog'
import SEO from '../marketing/SEO'

function readCompact() {
  try { return localStorage.getItem('dp_sidebar_compact') === '1' } catch { return false }
}

function NavItem({ item, compact, onNavigate }) {
  const location = useLocation()
  const Icon = item.icon
  const custom = item.match ? item.match(location.pathname) : null
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      data-tooltip={compact ? item.label : undefined}
      data-tooltip-side="right"
      aria-label={compact ? item.label : undefined}
      className={({ isActive }) => {
        const active = custom ?? isActive
        return cx(
          'group flex items-center gap-3 rounded-md text-base font-medium transition-colors duration-fast',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
          compact ? 'h-10 w-10 justify-center' : 'h-9 px-2.5',
          active ? 'bg-primary-soft text-primary-text' : 'text-muted hover:bg-ink/[0.06] hover:text-fg',
        )
      }}
    >
      <Icon className="h-[18px] w-[18px] flex-shrink-0" aria-hidden="true" />
      {!compact && <span className="truncate">{item.label}</span>}
    </NavLink>
  )
}

function SidebarContent({ compact, onNavigate, onUpload, onToggleCompact, isDrawer, onCloseDrawer }) {
  return (
    <div className="flex h-full flex-col">
      <div className={cx('flex h-14 flex-shrink-0 items-center border-b border-line', compact ? 'justify-center px-2' : 'justify-between px-3')}>
        <Link to="/app" onClick={onNavigate} className="flex items-center gap-2.5 rounded-md focus-ring" aria-label="Tallis home">
          <LogoMark size={28} />
          {!compact && <Wordmark />}
        </Link>
        {isDrawer ? (
          <IconButton icon={X} label="Close menu" onClick={onCloseDrawer} tooltip={false} />
        ) : !compact ? (
          <IconButton icon={ChevronsLeft} label="Collapse sidebar" size="sm" onClick={onToggleCompact} />
        ) : null}
      </div>

      <div className={cx('flex-shrink-0 pt-3', compact ? 'px-2' : 'px-3')}>
        <button
          type="button"
          onClick={onUpload}
          data-tooltip={compact ? 'Upload data' : undefined}
          data-tooltip-side="right"
          aria-label={compact ? 'Upload data' : undefined}
          className={cx('btn-primary w-full', compact && 'btn-icon h-10 w-10')}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          {!compact && 'Upload data'}
        </button>
      </div>

      <nav aria-label="Workspace" className={cx('flex-1 overflow-y-auto py-3', compact ? 'px-2' : 'px-3')}>
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className={cx(gi > 0 && 'mt-5')}>
            {group.label && !compact && (
              <p className="mb-1 px-2.5 text-xs font-medium text-subtle">{group.label}</p>
            )}
            {group.label && compact && <div className="mx-auto mb-2 h-px w-6 bg-line" aria-hidden="true" />}
            <ul className={cx('flex flex-col gap-0.5', compact && 'items-center')}>
              {group.items.map((item) => (
                <li key={item.to}><NavItem item={item} compact={compact} onNavigate={onNavigate} /></li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cx('flex-shrink-0 border-t border-line py-3', compact ? 'px-2' : 'px-3')}>
        <ul className={cx('flex flex-col gap-0.5', compact && 'items-center')}>
          {FOOTER_ITEMS.map((item) => (
            <li key={item.to}><NavItem item={item} compact={compact} onNavigate={onNavigate} /></li>
          ))}
        </ul>
        {compact && !isDrawer && (
          <div className="mt-2 flex justify-center">
            <IconButton icon={ChevronsRight} label="Expand sidebar" size="sm" tooltipSide="right" onClick={onToggleCompact} />
          </div>
        )}
      </div>
    </div>
  )
}

export default function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { isGuest, isAuthenticated } = useAuth()
  const [compact, setCompact] = useState(readCompact)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [authModal, setAuthModal] = useState({ open: false, tab: 'login' })
  // Guests choose once per session between a free account and a temporary guest workspace.
  const [choiceMade, setChoiceMade] = useState(guestChoiceMade)
  const showGuestChoice = isGuest && !isAuthenticated && !choiceMade && !authModal.open
  const drawerRef = useRef(null)
  const menuButtonRef = useRef(null)

  // Restore the workspace's datasets into the session after a page reload.
  const hydrateFiles = useDataPilot((st) => st.hydrateFiles)
  useEffect(() => { hydrateFiles?.() }, [hydrateFiles])

  const toggleCompact = useCallback(() => {
    setCompact((c) => {
      try { localStorage.setItem('dp_sidebar_compact', c ? '0' : '1') } catch { /* ignore */ }
      return !c
    })
  }, [])

  // Global shortcuts: Ctrl/Cmd+K opens search, Ctrl/Cmd+U opens upload.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen((v) => !v) }
      if (mod && e.key.toLowerCase() === 'u') { e.preventDefault(); setUploadOpen(true) }
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Close the drawer on navigation; move focus into it when it opens.
  useEffect(() => { setDrawerOpen(false) }, [location.pathname])
  useEffect(() => {
    if (drawerOpen) {
      document.body.classList.add('mobile-nav-open')
      window.setTimeout(() => drawerRef.current?.querySelector('a,button')?.focus(), 30)
    } else {
      document.body.classList.remove('mobile-nav-open')
    }
  }, [drawerOpen])

  // Allow any page to open the upload dialog (e.g. empty states).
  useEffect(() => {
    const open = () => setUploadOpen(true)
    window.addEventListener('dp:open-upload', open)
    return () => window.removeEventListener('dp:open-upload', open)
  }, [])

  const title = pageTitle(location.pathname)

  return (
    <div className="flex h-[100dvh] overflow-hidden bg-bg text-fg">
      <SEO title="Workspace" description="Private Tallis analytics workspace." canonicalPath="/app" noindex />
      <a href="#main-content" className="skip-link">Skip to content</a>

      {/* Desktop sidebar */}
      <aside
        className={cx(
          'hidden flex-shrink-0 border-r border-line bg-surface transition-[width] duration-base lg:block',
          compact ? 'w-[64px]' : 'w-[232px]',
        )}
        aria-label="Sidebar"
      >
        <SidebarContent compact={compact} onUpload={() => setUploadOpen(true)} onToggleCompact={toggleCompact} />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-black/40 animate-fade-in"
            aria-label="Close menu"
            tabIndex={-1}
            onClick={() => { setDrawerOpen(false); menuButtonRef.current?.focus() }}
          />
          <div ref={drawerRef} className="pt-safe absolute inset-y-0 left-0 w-[min(84vw,300px)] border-r border-line bg-surface shadow-dialog animate-slide-up">
            <SidebarContent
              compact={false}
              isDrawer
              onNavigate={() => setDrawerOpen(false)}
              onCloseDrawer={() => { setDrawerOpen(false); menuButtonRef.current?.focus() }}
              onUpload={() => { setDrawerOpen(false); setUploadOpen(true) }}
            />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="pt-safe flex-shrink-0 border-b border-line bg-surface">
          <div className="flex h-14 items-center gap-2 px-3 sm:px-4">
            <IconButton
              ref={menuButtonRef}
              icon={Menu}
              label="Open menu"
              tooltip={false}
              className="lg:hidden"
              onClick={() => setDrawerOpen(true)}
              aria-expanded={drawerOpen}
            />
            <Link to="/app" className="flex items-center rounded-md focus-ring lg:hidden" aria-label="Tallis home">
              <LogoMark size={26} />
            </Link>
            <h1 className="min-w-0 truncate pl-1 text-md font-semibold text-fg lg:pl-0">{title}</h1>

            <div className="ml-auto flex items-center gap-1 sm:gap-2">
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="hidden h-9 w-64 items-center gap-2 rounded-md border border-line bg-bg px-2.5 text-sm text-subtle transition-colors hover:border-line-strong md:flex focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
              >
                <Search className="h-4 w-4" aria-hidden="true" />
                <span className="flex-1 text-left">Search or jump to…</span>
                <kbd className="kbd">Ctrl K</kbd>
              </button>
              <IconButton icon={Search} label="Search" className="md:hidden" onClick={() => setPaletteOpen(true)} />
              <ThemeToggle />
              <UserMenu onSettings={() => navigate('/app/settings/profile')} />
            </div>
          </div>
        </header>

        {isGuest && !isAuthenticated && (
          <GuestBanner
            onSignUp={() => setAuthModal({ open: true, tab: 'signup' })}
            onLogin={() => setAuthModal({ open: true, tab: 'login' })}
          />
        )}

        <main id="main-content" className="min-h-0 flex-1 overflow-hidden" tabIndex={-1}>
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <CommandPalette isOpen={paletteOpen} onClose={() => setPaletteOpen(false)} onUpload={() => setUploadOpen(true)} />
      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <GuestChoiceDialog
        open={showGuestChoice}
        onClose={() => setChoiceMade(true)}
        onSignUp={() => setAuthModal({ open: true, tab: 'signup' })}
        onSignIn={() => setAuthModal({ open: true, tab: 'login' })}
        onSampleLoaded={() => navigate('/app/analyze', { state: { suggestedPrompt: SAMPLE_QUESTIONS[0] } })}
      />
      <AuthModal open={authModal.open} onClose={() => setAuthModal((s) => ({ ...s, open: false }))} defaultTab={authModal.tab} />
      <ToastContainer />
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="h-full overflow-hidden p-4 sm:p-6" role="status" aria-label="Loading page">
      <div className="skeleton h-7 w-48" />
      <div className="skeleton mt-3 h-4 w-80 max-w-full" />
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
      </div>
      <div className="skeleton mt-4 h-64" />
    </div>
  )
}
