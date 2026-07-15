import React, { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDataPilot } from '../hooks/useDataPilot'
import { useAuth } from '../contexts/AuthContext'

export default function DashboardHome() {
  const { files, historyMessages, historyTotal, reports, trackEvent, loadHistory, loadReports } = useDataPilot()
  const { user } = useAuth()
  const navigate = useNavigate()

  // Load history and reports so checklist and stats are accurate
  useEffect(() => {
    loadHistory?.()
    loadReports?.()
  }, [])

  const queryCount = historyTotal || historyMessages?.length || 0

  // Calculate setup checklist progress
  const checklist = [
    { id: 'signup', label: 'Create your account', completed: true, desc: 'Completed on registration' },
    { id: 'dataset', label: 'Upload your first dataset', completed: files.length > 0, desc: 'CSV or Excel spreadsheet', link: '/app/datasets' },
    { id: 'query', label: 'Ask your first analytics question', completed: queryCount > 0, desc: 'Natural language analysis', link: '/app/analyze' },
    { id: 'report', label: 'Generate a narrative report', completed: reports && reports.length > 0, desc: 'Create summary document', link: '/app/report' }
  ]

  const completedCount = checklist.filter(item => item.completed).length
  const progressPercent = Math.round((completedCount / checklist.length) * 100)

  return (
    <div className="h-full overflow-y-auto px-8 py-8 custom-scrollbar bg-[#030712]">
      {/* Welcome Banner */}
      <div className="mb-8">
        <h2 className="text-xl font-bold text-white tracking-tight">
          Welcome back, {user?.full_name || 'Explorer'} 👋
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Here is your analytics command center. Follow the checklist below to unlock full insights.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Onboarding Checklist Section */}
        <div className="lg:col-span-2 glass-panel p-6 rounded-2xl border border-white/5 bg-slate-900/10">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">Getting Started Checklist</h3>
            <span className="text-xs font-mono font-bold text-brand-400 bg-brand-500/10 px-2 py-0.5 rounded-lg border border-brand-500/20">
              {progressPercent}% Complete
            </span>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-[#0d1222] rounded-full h-1.5 mb-6 overflow-hidden border border-white/5">
            <div 
              className="bg-gradient-to-r from-brand-500 to-purple-600 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          <div className="space-y-4">
            {checklist.map((item, idx) => (
              <div 
                key={item.id} 
                className={`flex items-start gap-4 p-4 rounded-xl border transition-all duration-150 ${
                  item.completed 
                    ? 'bg-slate-900/20 border-emerald-500/10' 
                    : 'bg-[#0d1222] border-white/5 hover:border-brand-500/25 cursor-pointer'
                }`}
                onClick={() => {
                  if (!item.completed && item.link) {
                    trackEvent('ONBOARDING_CHECKLIST_CLICK', `User clicked checklist item '${item.id}'`)
                    navigate(item.link)
                  }
                }}
              >
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold border ${
                  item.completed 
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/35' 
                    : 'bg-white/5 text-slate-500 border-white/10'
                }`}>
                  {item.completed ? '✓' : idx + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className={`text-xs font-semibold leading-none ${item.completed ? 'text-slate-400 line-through' : 'text-slate-200'}`}>
                    {item.label}
                  </h4>
                  <p className="text-[10px] text-slate-500 mt-1">{item.desc}</p>
                </div>
                {!item.completed && item.link && (
                  <span className="text-[10px] text-brand-400 hover:text-brand-300 font-medium">
                    Start →
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Quick Stats Sidebar */}
        <div className="space-y-6">
          {/* Usage Quick-Check */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 bg-slate-900/10">
            <h3 className="text-sm font-semibold text-white mb-4">Workspace Stats</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-[#0d1222] p-3 rounded-xl border border-white/5">
                <span className="text-[10px] text-slate-500 block">Uploaded Datasets</span>
                <span className="text-base font-bold text-white mt-1 block font-mono">{files.length}</span>
              </div>
              <div className="bg-[#0d1222] p-3 rounded-xl border border-white/5">
                <span className="text-[10px] text-slate-500 block">Total Queries Run</span>
                <span className="text-base font-bold text-white mt-1 block font-mono">{queryCount}</span>
              </div>
            </div>
            <Link 
              to="/app/billing" 
              className="mt-4 w-full flex items-center justify-center py-2 bg-white/5 hover:bg-white/10 text-slate-300 rounded-xl text-xs font-semibold transition-all border border-white/5"
            >
              View Quotas & Billing →
            </Link>
          </div>

          {/* Quick Actions */}
          <div className="glass-panel p-6 rounded-2xl border border-white/5 bg-slate-900/10">
            <h3 className="text-sm font-semibold text-white mb-3">Quick Navigation</h3>
            <div className="space-y-2">
              <Link 
                to="/app/analyze" 
                className="w-full flex items-center justify-between p-3 bg-[#0d1222] hover:bg-slate-900/30 rounded-xl text-xs font-medium text-slate-300 border border-white/5 transition-all"
              >
                <span>💬 Start New Analysis Chat</span>
                <span className="text-slate-500">→</span>
              </Link>
              <Link 
                to="/app/datasets" 
                className="w-full flex items-center justify-between p-3 bg-[#0d1222] hover:bg-slate-900/30 rounded-xl text-xs font-medium text-slate-300 border border-white/5 transition-all"
              >
                <span>📦 Manage Datasets</span>
                <span className="text-slate-500">→</span>
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
