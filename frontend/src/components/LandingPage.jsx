import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useDataPilot } from '../hooks/useDataPilot'

export default function LandingPage() {
  const navigate = useNavigate()
  const { initGuestSession } = useAuth()
  const { uploadFile } = useDataPilot()

  const handleTryDemo = async () => {
    await initGuestSession()
    // Redirect to guest demo page
    navigate('/demo')
  }

  const handleFileUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    await initGuestSession()
    navigate('/app/analyze')
    // We will automatically upload the file once the hook mounts in /app/analyze
    setTimeout(() => {
      useDataPilot.getState().uploadFile(file)
    }, 500)
  }

  const faqItems = [
    {
      q: "Does my data leave my local machine?",
      a: "DataPilot processes your calculations locally in memory. For AI features, you can connect your own encrypted API keys (Gemini, OpenAI, Claude) which are encrypted at the application layer."
    },
    {
      q: "What file formats are supported?",
      a: "We support CSV (.csv) and Excel (.xlsx) spreadsheets of up to 100MB for premium plans."
    },
    {
      q: "Is there a free tier?",
      a: "Yes! Guest mode requires no signup and lets you ask up to 20 questions. Free accounts offer persistent workspaces with 20 uploads monthly."
    }
  ]

  return (
    <div className="min-h-screen overflow-y-auto bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
      {/* Ambient background glows */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden z-0">
        <div className="ambient-glow top-[-20%] left-[-15%] opacity-15"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)' }} />
        <div className="ambient-glow bottom-[-10%] right-[-10%] opacity-10"
          style={{ background: 'radial-gradient(circle, #8b5cf6 0%, transparent 70%)' }} />
      </div>

      {/* Navigation Header */}
      <header className="w-full max-w-7xl mx-auto px-6 py-5 flex items-center justify-between z-10 relative">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shadow-lg border border-brand-500/25 bg-gradient-to-br from-brand-600 to-purple-600">
            🧭
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-white leading-none">DataPilot</h1>
            <p className="text-[9px] text-slate-500 mt-1 font-mono">SaaS Analytics Platform</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <Link to="/login" className="text-xs text-slate-400 hover:text-slate-200 transition-colors font-medium">
            Sign In
          </Link>
          <Link to="/signup" className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold">
            Get Started Free
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section className="flex-1 max-w-5xl mx-auto px-6 pt-16 pb-20 text-center flex flex-col items-center justify-center z-10 relative">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-brand-500/20 bg-brand-500/5 text-[10px] text-brand-300 font-semibold mb-6">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-brand-500"></span>
          </span>
          Phase 3 Beta: Production-Ready Billing & Auth Online
        </div>

        <h2 className="text-4xl md:text-5xl font-black tracking-tight leading-[1.15] max-w-3xl text-white">
          Ask questions of your <span className="gradient-text">Spreadsheets</span>. Receive trusted answers in seconds.
        </h2>
        <p className="text-slate-400 text-sm md:text-base mt-6 max-w-2xl leading-relaxed">
          Upload your CSV or Excel file, ask questions in plain English, and receive explanatory answers, plotted charts, and narrative reports instantly.
        </p>

        {/* CTA Cards */}
        <div className="mt-12 grid grid-cols-1 sm:grid-cols-2 gap-6 w-full max-w-2xl">
          {/* Upload CTA */}
          <div className="glass hover:border-brand-500/35 transition-all duration-300 p-6 rounded-2xl flex flex-col items-center text-center relative group">
            <div className="text-3xl mb-4 group-hover:scale-110 transition-transform">📂</div>
            <h3 className="text-sm font-bold text-slate-200">Try with your file</h3>
            <p className="text-xs text-slate-500 mt-2 mb-6">Upload a CSV or XLSX spreadsheet directly</p>
            <label className="btn-primary w-full cursor-pointer text-xs py-2 rounded-xl font-semibold">
              Select spreadsheet
              <input type="file" onChange={handleFileUpload} accept=".csv,.xlsx" className="hidden" />
            </label>
          </div>

          {/* Demo CTA */}
          <div className="glass hover:border-brand-500/35 transition-all duration-300 p-6 rounded-2xl flex flex-col items-center text-center relative group">
            <div className="text-3xl mb-4 group-hover:scale-110 transition-transform">⚡</div>
            <h3 className="text-sm font-bold text-slate-200">Use demo dataset</h3>
            <p className="text-xs text-slate-500 mt-2 mb-6">Explore the full workspace with dummy sales data</p>
            <button onClick={handleTryDemo} className="btn-accent w-full py-2 rounded-xl text-xs font-semibold border-0">
              Load demo workspace
            </button>
          </div>
        </div>
      </section>

      {/* Feature grid */}
      <section className="border-t border-white/5 py-20 bg-black/10 z-10 relative">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="glass p-6 rounded-xl border border-white/5">
            <div className="text-brand-400 text-lg mb-3">💬</div>
            <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider">Conversational SQL</h4>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              No need to remember pivot tables or complex formulas. Type what you want to calculate, and receive answers with SQL transcripts.
            </p>
          </div>
          <div className="glass p-6 rounded-xl border border-white/5">
            <div className="text-blue-400 text-lg mb-3">📈</div>
            <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider">Custom Charts</h4>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Dynamically generates interactive charts that match your layout and branding constraints directly.
            </p>
          </div>
          <div className="glass p-6 rounded-xl border border-white/5">
            <div className="text-purple-400 text-lg mb-3">🔒</div>
            <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider">Data Privacy & Security</h4>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Your API keys are encrypted at the application layer with AES-256 (Fernet) keys. Plaintext keys are never stored.
            </p>
          </div>
        </div>
      </section>

      {/* Pricing Preview */}
      <section className="border-t border-white/5 py-20 z-10 relative">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h3 className="text-2xl font-extrabold text-white">Simple, transparent pricing</h3>
          <p className="text-xs text-slate-500 mt-2">Scale seamlessly from guest mode up to enterprise teams</p>
          
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-12">
            {/* Free Plan */}
            <div className="glass p-6 rounded-xl text-left border border-white/5 flex flex-col justify-between">
              <div>
                <h4 className="text-xs font-bold text-slate-400">Free</h4>
                <div className="text-2xl font-black mt-2 text-white">$0</div>
                <ul className="text-[10px] text-slate-500 space-y-2 mt-4">
                  <li>• 20 uploads / mo</li>
                  <li>• 200 queries</li>
                  <li>• 500MB storage limit</li>
                </ul>
              </div>
              <Link to="/signup" className="btn-ghost w-full text-center mt-6 py-2 rounded-xl bg-white/5">Sign Up</Link>
            </div>

            {/* Pro Plan */}
            <div className="glass border-brand-500/30 p-6 rounded-xl text-left flex flex-col justify-between relative">
              <div className="absolute top-2 right-2 bg-brand-500/10 text-brand-400 border border-brand-500/20 rounded-full px-2 py-0.5 text-[8px] font-bold">POPULAR</div>
              <div>
                <h4 className="text-xs font-bold text-brand-300">Pro</h4>
                <div className="text-2xl font-black mt-2 text-white">$19<span className="text-xs font-medium text-slate-500">/mo</span></div>
                <ul className="text-[10px] text-slate-400 space-y-2 mt-4">
                  <li>• Unlimited uploads</li>
                  <li>• Unlimited queries</li>
                  <li>• 10GB storage limit</li>
                  <li>• Custom API Key support</li>
                </ul>
              </div>
              <Link to="/signup" className="btn-primary w-full text-center mt-6 py-2 rounded-xl">Get Pro</Link>
            </div>

            {/* Enterprise Plan */}
            <div className="glass p-6 rounded-xl text-left border border-white/5 flex flex-col justify-between">
              <div>
                <h4 className="text-xs font-bold text-slate-400">Enterprise</h4>
                <div className="text-2xl font-black mt-2 text-white">Custom</div>
                <ul className="text-[10px] text-slate-500 space-y-2 mt-4">
                  <li>• Dedicated instances</li>
                  <li>• SSO / SAML integration</li>
                  <li>• SLA agreements</li>
                </ul>
              </div>
              <a href="mailto:sales@datapilot.ai" className="btn-ghost w-full text-center mt-6 py-2 rounded-xl bg-white/5">Contact Sales</a>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section className="border-t border-white/5 py-20 bg-black/10 z-10 relative">
        <div className="max-w-3xl mx-auto px-6">
          <h3 className="text-xl font-bold text-white text-center mb-12">Frequently Asked Questions</h3>
          <div className="space-y-6">
            {faqItems.map((item, idx) => (
              <div key={idx} className="glass p-5 rounded-xl border border-white/5">
                <h4 className="text-xs font-bold text-slate-200">{item.q}</h4>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">{item.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="w-full max-w-7xl mx-auto px-6 py-8 border-t border-white/5 z-10 relative flex flex-wrap items-center justify-between gap-4 text-[10px] text-slate-600">
        <div>© 2026 DataPilot. All rights reserved.</div>
        <div className="flex gap-4">
          <Link to="/legal/privacy" className="hover:text-slate-400">Privacy Policy</Link>
          <Link to="/legal/terms" className="hover:text-slate-400">Terms of Service</Link>
        </div>
      </footer>
    </div>
  )
}
