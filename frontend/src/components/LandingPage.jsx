import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useDataPilot } from '../hooks/useDataPilot'

export default function LandingPage() {
  const navigate = useNavigate()
  const { initGuestSession } = useAuth()
  const [activeFAQ, setActiveFAQ] = useState(null)

  const handleTryDemo = async () => {
    await initGuestSession()
    navigate('/demo')
  }

  const handleFileUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    await initGuestSession()
    navigate('/app/analyze')
    setTimeout(() => {
      useDataPilot.getState().uploadFile(file)
    }, 500)
  }

  const toggleFAQ = (idx) => {
    setActiveFAQ(activeFAQ === idx ? null : idx)
  }

  const faqItems = [
    {
      q: "Does my data leave my local machine?",
      a: "DataPilot processes your calculations locally in memory using an embedded high-speed DuckDB client. For AI insights, we securely interface with LLMs (Gemini, OpenAI, Claude). You can also connect your own API keys, which are AES-encrypted at the application layer before storage. We never sell or store your data."
    },
    {
      q: "What file formats are supported?",
      a: "We support CSV (.csv) and Excel (.xlsx) spreadsheets. Multi-sheet workbooks are fully supported: DataPilot automatically profiles columns across all sheets and lets you query them in plain English."
    },
    {
      q: "How does the AI auto-recovery work?",
      a: "If a database execution fails (e.g. column typo or mismatched sheet name), DataPilot's agent automatically fuzzy matches column schemas, attempts self-repair, and notifies you of the corrected columns used. It is designed to never let query execution crash."
    },
    {
      q: "Can I host this locally?",
      a: "Yes! DataPilot has a built-in Ollama adapter. By selecting the Ollama provider, you can run all natural language models locally on your own hardware, ensuring complete compliance and offline operation."
    },
    {
      q: "What are the limits on the Free tier?",
      a: "The Free tier includes 20 persistent uploads monthly, 200 conversational queries, and up to 500MB of storage. It is perfect for personal analysts, indie developers, and startup founders."
    },
    {
      q: "Is it easy to cancel my subscription?",
      a: "Absolutely. You can manage your billing, download receipts, or cancel your subscription at any time using the Stripe Customer Portal inside your account settings with a single click."
    }
  ]

  const features = [
    {
      icon: "💬",
      title: "Conversational Chat",
      desc: "Ask questions naturally like 'Compare Q1 sales vs Q2 sales by category' and get instant formatted answers."
    },
    {
      icon: "📊",
      title: "Dynamic Charting",
      desc: "Receive interactive charts (bar, line, scatter) automatically mapped to your query parameters."
    },
    {
      icon: "🧹",
      title: "AI Data Cleaning",
      desc: "Identify quality issues, clean null values, handle date formatting, and detect outliers automatically."
    },
    {
      icon: "⚡",
      title: "DuckDB Speed Engine",
      desc: "Enjoy sub-second queries on millions of rows powered by an embedded columnar database engine."
    },
    {
      icon: "💡",
      title: "Logic Explainability",
      desc: "Full transparency. Inspect the generated DuckDB SQL query, used columns, and reasoning logic in a side drawer."
    },
    {
      icon: "🔒",
      title: "Client-Key Encryption",
      desc: "All API keys are encrypted at the application layer with AES-256 (Fernet) keys. Plain text keys are never stored."
    }
  ]

  const steps = [
    {
      step: "01",
      title: "Upload Dataset",
      desc: "Drag & drop your CSV or Excel workbook. We automatically run diagnostics and profile your columns."
    },
    {
      step: "02",
      title: "Ask & Filter",
      desc: "Type questions in plain English. The AI agent translates prompts to optimized SQL, executes them, and builds charts."
    },
    {
      step: "03",
      title: "Export & Report",
      desc: "Generate narrative executive summaries, export results to Excel/CSV, or share saved analysis dashboards."
    }
  ]

  return (
    <div className="h-screen overflow-y-auto bg-[#030712] text-slate-100 flex flex-col font-sans select-none custom-scrollbar">
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
      <section className="max-w-5xl mx-auto px-6 pt-16 pb-20 text-center flex flex-col items-center justify-center z-10 relative">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-brand-500/20 bg-brand-500/5 text-[10px] text-brand-300 font-semibold mb-6">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-brand-500"></span>
          </span>
          Next-Gen AI Spreadsheet Analytics Engine
        </div>

        <h2 className="text-4xl md:text-6xl font-black tracking-tight leading-[1.1] max-w-4xl text-white">
          Ditch pivot tables. Chat with your <span className="gradient-text">Spreadsheets</span> naturally.
        </h2>
        <p className="text-slate-400 text-sm md:text-base mt-6 max-w-3xl leading-relaxed">
          Upload any CSV or Excel file, ask complex questions in plain English, and receive explanatory answers, interactive charts, and executive narrative briefs in seconds.
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

      {/* Comparisons Section */}
      <section className="border-t border-white/5 py-20 bg-black/10 z-10 relative">
        <div className="max-w-4xl mx-auto px-6">
          <div className="text-center mb-12">
            <h3 className="text-xl md:text-2xl font-bold text-white tracking-tight">Why switch to DataPilot?</h3>
            <p className="text-xs text-slate-500 mt-1">Compare the old way of doing analytics with DataPilot's agentic model.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="p-6 rounded-2xl bg-slate-900/5 border border-white/5 space-y-4">
              <h4 className="text-xs font-bold text-rose-400 uppercase tracking-wider flex items-center gap-2">
                ❌ Traditional Spreadsheets (Excel/Sheets)
              </h4>
              <ul className="text-xs text-slate-400 space-y-3 font-medium">
                <li>• Writing nested IF, VLOOKUP, or INDEX MATCH formulas by hand.</li>
                <li>• Spending hours structuring charts and formatting reports.</li>
                <li>• Manual script scripting (VBA/Python) for outliers.</li>
                <li>• Staring at massive rows hoping you didn't break a calculation cells reference.</li>
              </ul>
            </div>
            <div className="p-6 rounded-2xl bg-brand-500/[0.02] border border-brand-500/20 space-y-4">
              <h4 className="text-xs font-bold text-brand-300 uppercase tracking-wider flex items-center gap-2">
                🚀 DataPilot AI Engine
              </h4>
              <ul className="text-xs text-slate-300 space-y-3 font-semibold">
                <li>• **Conversational agent**: Just type what you want to calculate in plain English.</li>
                <li>• **Automated insights**: Dynamic line/bar charting built on query outputs.</li>
                <li>• **AI self-healing**: Auto-repairs schema typos or misspelled sheet constraints.</li>
                <li>• **Explainability trace**: Full SQL and logical explanations are always visible.</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* How it Works Timeline */}
      <section className="border-t border-white/5 py-20 z-10 relative">
        <div className="max-w-5xl mx-auto px-6">
          <div className="text-center mb-16">
            <h3 className="text-xl md:text-2xl font-bold text-white tracking-tight">How it works</h3>
            <p className="text-xs text-slate-500 mt-1">Three simple steps to unlock tabular data insights.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {steps.map(step => (
              <div key={step.step} className="flex flex-col relative p-6 rounded-xl border border-white/5 bg-[#0d1222]/30">
                <span className="text-3xl font-black text-brand-500/20 font-mono mb-4">{step.step}</span>
                <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider">{step.title}</h4>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Full Feature Grid */}
      <section className="border-t border-white/5 py-20 bg-black/10 z-10 relative">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h3 className="text-xl md:text-2xl font-bold text-white tracking-tight">Complete SaaS Analytics Toolkit</h3>
            <p className="text-xs text-slate-500 mt-1">DataPilot comes packed with premium enterprise features out of the box.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {features.map(f => (
              <div key={f.title} className="glass p-6 rounded-xl border border-white/5 hover:border-brand-500/20 transition-all duration-200">
                <div className="text-xl mb-3">{f.icon}</div>
                <h4 className="text-xs font-bold text-slate-200 uppercase tracking-wider">{f.title}</h4>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
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
                <ul className="text-[10px] text-slate-500 space-y-2.5 mt-4">
                  <li>• 20 uploads / mo</li>
                  <li>• 200 conversational queries</li>
                  <li>• 500MB storage limit</li>
                  <li>• Team members limit: 1</li>
                </ul>
              </div>
              <Link to="/signup" className="btn-ghost w-full text-center mt-6 py-2 rounded-xl bg-white/5">Sign Up</Link>
            </div>

            {/* Pro Plan */}
            <div className="glass border-brand-500/30 p-6 rounded-xl text-left flex flex-col justify-between relative bg-brand-500/[0.01]">
              <div className="absolute top-2 right-2 bg-brand-500/10 text-brand-400 border border-brand-500/20 rounded-full px-2 py-0.5 text-[8px] font-bold">POPULAR</div>
              <div>
                <h4 className="text-xs font-bold text-brand-300">Pro</h4>
                <div className="text-2xl font-black mt-2 text-white">$19<span className="text-xs font-medium text-slate-500">/mo</span></div>
                <ul className="text-[10px] text-slate-300 space-y-2.5 mt-4">
                  <li>• **Unlimited uploads**</li>
                  <li>• **Unlimited queries**</li>
                  <li>• **10GB storage limit**</li>
                  <li>• AES-encrypted API keys</li>
                  <li>• Advanced spreadsheet grids</li>
                </ul>
              </div>
              <Link to="/signup" className="btn-primary w-full text-center mt-6 py-2 rounded-xl">Get Pro</Link>
            </div>

            {/* Enterprise Plan */}
            <div className="glass p-6 rounded-xl text-left border border-white/5 flex flex-col justify-between">
              <div>
                <h4 className="text-xs font-bold text-slate-400">Enterprise</h4>
                <div className="text-2xl font-black mt-2 text-white">Custom</div>
                <ul className="text-[10px] text-slate-500 space-y-2.5 mt-4">
                  <li>• Dedicated memory buffers</li>
                  <li>• SSO / SAML integration</li>
                  <li>• SLA agreement support</li>
                  <li>• Custom limits config</li>
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
          <div className="space-y-4">
            {faqItems.map((item, idx) => (
              <div key={idx} className="glass rounded-xl border border-white/5 overflow-hidden transition-all duration-300">
                <button 
                  onClick={() => toggleFAQ(idx)}
                  className="w-full text-left px-5 py-4 flex items-center justify-between text-xs font-bold text-slate-200 hover:bg-white/[0.01] transition-colors focus:outline-none"
                >
                  <span>{item.q}</span>
                  <span className="text-slate-500">{activeFAQ === idx ? '✕' : '＋'}</span>
                </button>
                {activeFAQ === idx && (
                  <div className="px-5 pb-4 text-xs text-slate-400 leading-relaxed border-t border-white/[0.03] pt-3 bg-black/5 animate-fade-in">
                    {item.a}
                  </div>
                )}
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
