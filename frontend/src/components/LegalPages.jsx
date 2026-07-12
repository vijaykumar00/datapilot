import React from 'react'
import { Link } from 'react-router-dom'

export function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-200 font-sans p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-between border-b border-white/5 pb-4">
          <Link to="/" className="text-xs text-brand-400 hover:underline">← Return Home</Link>
          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono">DRAFT — PENDING LEGAL REVIEW</span>
        </div>

        <h1 className="text-2xl font-black text-white">Privacy Policy</h1>
        <p className="text-xs text-slate-400 font-mono">Last Updated: July 2026</p>

        <section className="space-y-3.5 text-xs text-slate-300 leading-relaxed">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">1. Data Storage & Local Processing</h2>
          <p>
            DataPilot processes your calculations locally in memory. Stored files are retained inside your tenant workspace directory on the backend server.
          </p>

          <h2 className="text-sm font-bold text-white uppercase tracking-wider">2. Guest Data Expiration</h2>
          <p>
            Guest sessions and all associated uploaded spreadsheets expire automatically after 24 hours of inactivity. Permanent user account data is stored securely until requested for deletion.
          </p>

          <h2 className="text-sm font-bold text-white uppercase tracking-wider">3. Third-Party AI Integrations</h2>
          <p>
            When utilizing Gemini, OpenAI, or Claude providers, prompts are forwarded to the respective LLM API endpoint. No database files are used for training models. Stored API keys are encrypted at the application layer before storage.
          </p>

          <h2 className="text-sm font-bold text-white uppercase tracking-wider">4. Cookies & Trackers</h2>
          <p>
            We use functional session cookies and local storage tokens to persist authenticated states and preferences. No ad tracking networks are implemented. See our Cookie Policy for more details.
          </p>
        </section>
      </div>
    </div>
  )
}

export function TermsOfService() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-200 font-sans p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-between border-b border-white/5 pb-4">
          <Link to="/" className="text-xs text-brand-400 hover:underline">← Return Home</Link>
          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono">DRAFT — PENDING LEGAL REVIEW</span>
        </div>

        <h1 className="text-2xl font-black text-white">Terms of Service</h1>
        <p className="text-xs text-slate-400 font-mono">Last Updated: July 2026</p>

        <section className="space-y-3.5 text-xs text-slate-300 leading-relaxed">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">1. Usage Entitlements</h2>
          <p>
            DataPilot reserves the right to terminate guest or free-tier workspaces that violate storage quotas or system integrity.
          </p>

          <h2 className="text-sm font-bold text-white uppercase tracking-wider">2. Limitation of Liability</h2>
          <p>
            Calculations and generated reports are AI-driven. While DataPilot provides progressive mathematical proof details (explainability drawers), users must verify crucial financial figures independently.
          </p>
        </section>
      </div>
    </div>
  )
}

export function CookiePolicy() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-200 font-sans p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-between border-b border-white/5 pb-4">
          <Link to="/" className="text-xs text-brand-400 hover:underline">← Return Home</Link>
          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono">DRAFT — PENDING LEGAL REVIEW</span>
        </div>

        <h1 className="text-2xl font-black text-white">Cookie Policy</h1>
        <p className="text-xs text-slate-400 font-mono">Last Updated: July 2026</p>

        <section className="space-y-3.5 text-xs text-slate-300 leading-relaxed">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">1. Usage of Cookies</h2>
          <p>
            We only utilize functional session cookies and local browser storage to retain authentication tokens, theme configurations, and default workspaces. We do not run any behavioral ad targeting or tracking cookies.
          </p>
        </section>
      </div>
    </div>
  )
}

export function AcceptableUsePolicy() {
  return (
    <div className="min-h-screen bg-[#030712] text-slate-200 font-sans p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-between border-b border-white/5 pb-4">
          <Link to="/" className="text-xs text-brand-400 hover:underline">← Return Home</Link>
          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono">DRAFT — PENDING LEGAL REVIEW</span>
        </div>

        <h1 className="text-2xl font-black text-white">Acceptable Use Policy</h1>
        <p className="text-xs text-slate-400 font-mono">Last Updated: July 2026</p>

        <section className="space-y-3.5 text-xs text-slate-300 leading-relaxed">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">1. Resource Usage Boundaries</h2>
          <p>
            Users must not submit scripts or datasets containing malicious commands, virus attachments, or automated stress-test macros. Scraping, brute-forcing auth screens, or bypassing workspace isolates is strictly prohibited.
          </p>
        </section>
      </div>
    </div>
  )
}

