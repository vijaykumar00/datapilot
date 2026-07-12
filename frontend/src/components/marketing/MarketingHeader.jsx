import React, { useState } from 'react'
import { Link } from 'react-router-dom'

export default function MarketingHeader() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <header className="w-full max-w-7xl mx-auto px-6 py-5 flex items-center justify-between z-50 relative">
      {/* Brand logo */}
      <Link to="/" className="flex items-center gap-3 focus:outline-none focus:ring-2 focus:ring-brand-500/40 rounded-xl px-1.5 py-1">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shadow-lg border border-brand-500/25 bg-gradient-to-br from-brand-600 to-purple-600">
          🧭
        </div>
        <div>
          <h1 className="text-sm font-bold tracking-tight text-white leading-none">DataPilot</h1>
          <p className="text-[9px] text-slate-500 mt-1 font-mono">SaaS Analytics Platform</p>
        </div>
      </Link>

      {/* Desktop navigation links */}
      <nav className="hidden md:flex items-center gap-6 text-xs font-semibold text-slate-400">
        <Link to="/features" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Features</Link>
        <Link to="/use-cases" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Use Cases</Link>
        <Link to="/security" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Security</Link>
        <Link to="/pricing" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Pricing</Link>
        <Link to="/about" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">About</Link>
        <Link to="/contact" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Contact</Link>
        <Link to="/docs" className="hover:text-slate-200 transition-colors focus:outline-none focus:text-slate-200">Docs</Link>
      </nav>

      {/* Desktop Auth CTAs */}
      <div className="hidden md:flex items-center gap-4">
        <Link to="/login" className="text-xs text-slate-400 hover:text-slate-200 transition-colors font-semibold focus:outline-none focus:text-slate-200">
          Sign In
        </Link>
        <Link to="/signup" className="btn-primary px-4 py-2 rounded-xl text-xs font-bold focus:outline-none focus:ring-2 focus:ring-brand-500/40">
          Get Started Free
        </Link>
      </div>

      {/* Mobile Toggle Button */}
      <button 
        onClick={() => setMobileOpen(!mobileOpen)}
        className="md:hidden text-slate-400 hover:text-slate-200 focus:outline-none text-xl p-1"
        aria-label="Toggle menu"
      >
        {mobileOpen ? '✕' : '☰'}
      </button>

      {/* Mobile Drawer Menu */}
      {mobileOpen && (
        <div className="absolute top-full left-0 right-0 mt-2 mx-6 p-5 glass rounded-2xl border border-white/10 bg-[#080c18] flex flex-col gap-4 z-50 animate-fade-in md:hidden shadow-2xl">
          <Link to="/features" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Features</Link>
          <Link to="/use-cases" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Use Cases</Link>
          <Link to="/security" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Security</Link>
          <Link to="/pricing" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Pricing</Link>
          <Link to="/about" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">About</Link>
          <Link to="/contact" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Contact</Link>
          <Link to="/docs" onClick={() => setMobileOpen(false)} className="text-xs font-semibold text-slate-300 hover:text-white py-1">Docs</Link>
          <div className="border-t border-white/5 pt-3 mt-1 flex flex-col gap-3">
            <Link to="/login" onClick={() => setMobileOpen(false)} className="text-center text-xs font-semibold text-slate-300 hover:text-white py-1.5">
              Sign In
            </Link>
            <Link to="/signup" onClick={() => setMobileOpen(false)} className="btn-primary text-center py-2.5 rounded-xl text-xs font-bold">
              Get Started Free
            </Link>
          </div>
        </div>
      )}
    </header>
  )
}
