import { useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { ThemeToggle } from '../shell/ThemeToggle'
import { marketingNavItems } from '../../data/marketing'
import BrandLogo from './BrandLogo'
import MobileNavigation from './MobileNavigation'

export default function MarketingHeader() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const menuButtonRef = useRef(null)

  return (
    <header className="marketing-header">
      <div className="marketing-header-inner">
        <BrandLogo />

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary navigation">
          {marketingNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `marketing-nav-link ${isActive ? 'is-active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <ThemeToggle />
          <Link to="/login" className="btn-ghost">
            Sign in
          </Link>
          <Link to="/try-free" className="btn-primary">
            Try free
          </Link>
        </div>

        <button
          ref={menuButtonRef}
          type="button"
          className="btn-ghost btn-icon h-11 w-11 lg:hidden"
          aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
          aria-expanded={mobileOpen}
          aria-controls="mobile-navigation"
          onClick={() => setMobileOpen((value) => !value)}
        >
          {mobileOpen ? <X className="h-5 w-5" aria-hidden="true" /> : <Menu className="h-5 w-5" aria-hidden="true" />}
        </button>
      </div>

      <MobileNavigation
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        triggerRef={menuButtonRef}
      />
    </header>
  )
}
