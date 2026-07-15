import { useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
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

        <nav className="hidden items-center gap-1 md:flex" aria-label="Primary navigation">
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

        <div className="hidden items-center gap-3 md:flex">
          <Link to="/login" className="btn-ghost">
            Sign In
          </Link>
          <Link to="/signup" className="btn-primary">
            Try Free
          </Link>
        </div>

        <button
          ref={menuButtonRef}
          type="button"
          className="icon-button md:hidden"
          aria-label="Open navigation"
          aria-expanded={mobileOpen}
          aria-controls="mobile-navigation"
          onClick={() => setMobileOpen((value) => !value)}
        >
          <span aria-hidden="true">{mobileOpen ? 'x' : 'menu'}</span>
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
