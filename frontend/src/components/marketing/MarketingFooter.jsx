import React from 'react'
import { Link } from 'react-router-dom'

export default function MarketingFooter() {
  return (
    <footer className="w-full border-t border-white/5 bg-black/10 z-10 relative">
      <div className="max-w-7xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
        {/* Brand Block */}
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center text-sm shadow-md border border-brand-500/25 bg-gradient-to-br from-brand-600 to-purple-600">
              🧭
            </div>
            <span className="text-xs font-bold text-white tracking-tight">DataPilot</span>
          </div>
          <p className="text-[10px] text-slate-500 mt-3 max-w-xs leading-relaxed">
            Next-generation conversational analytics, data profiling, and visual reporting for spreadsheet workbooks.
          </p>
        </div>

        {/* Product links */}
        <div className="flex flex-col gap-2">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">Product</span>
          <Link to="/features" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Features</Link>
          <Link to="/pricing" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Pricing</Link>
          <Link to="/security" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Security</Link>
        </div>

        {/* Resources links */}
        <div className="flex flex-col gap-2">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">Resources</span>
          <Link to="/docs" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Documentation</Link>
          <Link to="/contact" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Support & Contact</Link>
        </div>

        {/* Legal links */}
        <div className="flex flex-col gap-2">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-1">Legal</span>
          <Link to="/legal/privacy" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Privacy Policy</Link>
          <Link to="/legal/terms" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Terms of Service</Link>
          <Link to="/legal/cookie-policy" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Cookie Policy</Link>
          <Link to="/legal/acceptable-use" className="text-[10px] text-slate-400 hover:text-slate-200 transition-colors">Acceptable Use</Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 border-t border-white/5 flex flex-wrap items-center justify-between gap-4 text-[9px] text-slate-600">
        <div>© 2026 DataPilot. All rights reserved. Draft legal files require professional review before production launch.</div>
      </div>
    </footer>
  )
}
