import React, { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useDataPilot } from '../hooks/useDataPilot'

export default function SettingsLayout() {
  const { user } = useAuth()
  const location = useLocation()

  const navItems = [
    { path: '/app/settings/profile', label: '👤 Profile Settings' },
    { path: '/app/settings/workspace', label: '🏢 Workspace details' },
    { path: '/app/settings/members', label: '👥 Team members' },
    { path: '/app/settings/providers', label: '🤖 AI Providers & Keys' },
    { path: '/app/settings/security', label: '🔒 Security & Sessions' },
    { path: '/app/settings/billing', label: '💳 Billing & Quotas' }
  ]

  const getLinkClass = (path) => {
    const base = "flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-semibold transition-all duration-150 "
    const isActive = location.pathname === path
    return base + (isActive
      ? 'bg-brand-500/10 text-brand-300 border border-brand-500/20 shadow-sm'
      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent')
  }

  return (
    <div className="h-full flex overflow-hidden bg-[#030712]">
      {/* Settings Navigation Sidebar */}
      <aside className="w-60 border-r border-white/5 bg-[#050811]/40 flex flex-col flex-shrink-0">
        <div className="px-5 py-4 border-b border-white/5 select-none">
          <h2 className="text-xs font-bold text-white uppercase tracking-wider">Settings Settings</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">Manage your personal and workspace profile</p>
        </div>
        <nav className="p-3 space-y-1.5">
          {navItems.map(item => (
            <Link key={item.path} to={item.path} className={getLinkClass(item.path)}>
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>

      {/* Main Settings Sub-route Container */}
      <main className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
        <Outlet />
      </main>
    </div>
  )
}

// ── Settings Subcomponents ───────────────────────────────────────────────────

export function ProfileSettings() {
  const { user } = useAuth()
  const [name, setName] = useState(user?.full_name || '')
  const [email, setEmail] = useState(user?.email || '')
  const [saved, setSaved] = useState(false)

  const handleSave = (e) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-xl">
      <h3 className="text-base font-bold text-white mb-1">Profile Configuration</h3>
      <p className="text-slate-500 text-xs mb-6">Update your account display information.</p>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Full name</label>
          <input 
            type="text" 
            value={name} 
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-brand-500/35"
          />
        </div>
        <div>
          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Email address</label>
          <input 
            type="email" 
            value={email} 
            readOnly 
            className="w-full bg-[#0d1222]/50 border border-white/5 rounded-xl px-3 py-2 text-xs text-slate-400 cursor-not-allowed focus:outline-none"
          />
        </div>

        <button 
          type="submit"
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-semibold transition-all border border-brand-500/25 mt-4"
        >
          {saved ? 'Saved Successfully ✓' : 'Save Changes'}
        </button>
      </form>
    </div>
  )
}

export function WorkspaceSettings() {
  const { user } = useAuth()
  const [wsName, setWsName] = useState('My Analytics Workspace')
  const [wsSlug, setWsSlug] = useState('my-analytics-ws')
  const [saved, setSaved] = useState(false)

  const handleSave = (e) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-xl">
      <h3 className="text-base font-bold text-white mb-1">Workspace Configuration</h3>
      <p className="text-slate-500 text-xs mb-6">Manage organization profile settings and URL slug aliases.</p>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Workspace Name</label>
          <input 
            type="text" 
            value={wsName} 
            onChange={(e) => setWsName(e.target.value)}
            className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-brand-500/35"
          />
        </div>
        <div>
          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Workspace URL Slug</label>
          <div className="flex rounded-xl overflow-hidden border border-white/5 bg-[#0d1222]">
            <span className="bg-white/5 px-3 py-2 text-xs text-slate-500 select-none">datapilot.app/</span>
            <input 
              type="text" 
              value={wsSlug} 
              onChange={(e) => setWsSlug(e.target.value)}
              className="flex-1 bg-transparent px-3 py-2 text-xs text-white focus:outline-none"
            />
          </div>
        </div>

        <button 
          type="submit"
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-semibold transition-all border border-brand-500/25 mt-4"
        >
          {saved ? 'Saved Successfully ✓' : 'Save Changes'}
        </button>
      </form>
    </div>
  )
}

export function TeamMembersSettings() {
  const { user } = useAuth()
  const members = [
    { email: user?.email || 'admin@example.com', role: 'Owner (You)', status: 'Active' },
    { email: 'collaborator@example.com', role: 'Member', status: 'Pending Invite' }
  ]

  return (
    <div className="max-w-xl">
      <h3 className="text-base font-bold text-white mb-1">Team Organization</h3>
      <p className="text-slate-500 text-xs mb-6">Invite coworkers and configure RBAC roles.</p>

      <div className="bg-[#0d1222]/30 border border-white/5 rounded-xl overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-white/5 bg-[#050811]/50 text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              <th className="p-3">User</th>
              <th className="p-3">Role</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {members.map(member => (
              <tr key={member.email} className="border-b border-white/[0.03] text-xs text-slate-300">
                <td className="p-3 font-medium">{member.email}</td>
                <td className="p-3 text-slate-400">{member.role}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded-lg text-[9px] font-bold ${
                    member.status === 'Active' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/15' : 'bg-amber-500/10 text-amber-400 border border-amber-500/15'
                  }`}>
                    {member.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function ProvidersKeysSettings() {
  const { provider, setProvider } = useDataPilot()
  const [keys, setKeys] = useState({
    gemini: '••••••••••••••••••••••',
    openai: '',
    anthropic: ''
  })
  const [saved, setSaved] = useState(false)

  const handleSave = (e) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-xl">
      <h3 className="text-base font-bold text-white mb-1">AI API Configurations</h3>
      <p className="text-slate-500 text-xs mb-6">Manage external LLM keys securely using AES-256 client encryption.</p>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Primary Provider</label>
          <select 
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-brand-500/35"
          >
            <option value="gemini">✨ Google Gemini Pro</option>
            <option value="openai">🤖 OpenAI GPT-4</option>
            <option value="claude">🎭 Anthropic Claude 3.5</option>
            <option value="ollama">❄️ Local Ollama Instance</option>
          </select>
        </div>

        <div className="border-t border-white/5 pt-4 mt-4 space-y-4">
          <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wide">Encrypted API Keys</h4>
          <div>
            <label className="text-[10px] font-bold text-slate-500 block mb-1">Google Gemini API Key</label>
            <input 
              type="password" 
              value={keys.gemini}
              onChange={(e) => setKeys({...keys, gemini: e.target.value})}
              className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-brand-500/35"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold text-slate-500 block mb-1">OpenAI API Key</label>
            <input 
              type="password" 
              placeholder="sk-proj-..."
              value={keys.openai}
              onChange={(e) => setKeys({...keys, openai: e.target.value})}
              className="w-full bg-[#0d1222] border border-white/5 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-brand-500/35"
            />
          </div>
        </div>

        <button 
          type="submit"
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-semibold transition-all border border-brand-500/25 mt-4"
        >
          {saved ? 'Keys Saved ✓' : 'Save Config Keys'}
        </button>
      </form>
    </div>
  )
}

export function SecuritySessionsSettings() {
  const sessions = [
    { device: 'Chrome / Windows', ip: '127.0.0.1 (Localhost)', lastActive: 'Just Now', active: true }
  ]

  return (
    <div className="max-w-xl">
      <h3 className="text-base font-bold text-white mb-1">Security & Sessions</h3>
      <p className="text-slate-500 text-xs mb-6">Monitor active login sessions on your account.</p>

      <div className="bg-[#0d1222]/30 border border-white/5 rounded-xl overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-white/5 bg-[#050811]/50 text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              <th className="p-3">Device</th>
              <th className="p-3">IP Location</th>
              <th className="p-3">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session, idx) => (
              <tr key={idx} className="border-b border-white/[0.03] text-xs text-slate-300">
                <td className="p-3 font-medium">
                  {session.device}
                  {session.active && <span className="ml-2 text-[9px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.2 rounded font-bold border border-emerald-500/15">Active</span>}
                </td>
                <td className="p-3 text-slate-400 font-mono">{session.ip}</td>
                <td className="p-3 text-slate-500">{session.lastActive}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
