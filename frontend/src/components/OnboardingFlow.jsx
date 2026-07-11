import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function OnboardingFlow() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [useCase, setUseCase] = useState('')
  const [step, setStep] = useState(1)

  const useCases = [
    { id: 'sales', name: '📈 Sales & Revenue Analysis', desc: 'Identify top clients, sales trends, and profit margins.' },
    { id: 'marketing', name: '🎯 Marketing Campaigns', desc: 'Measure ROI, conversion rates, and client acquisition cost.' },
    { id: 'finance', name: '💰 Finance & Budgeting', desc: 'Track expense patterns, runaway costs, and cash flow projections.' },
    { id: 'operations', name: '⚙️ Operations & Supply Chain', desc: 'Diagnose inventory turn rates, shipping delays, and bottlenecks.' },
    { id: 'hr', name: '👥 Human Resources', desc: 'Evaluate department distributions, compensation ratios, and turnover.' },
    { id: 'general', name: '🔍 General Spreadsheet Audit', desc: 'Perform cleaning, profiling, and formula audits on raw data.' }
  ]

  const handleNext = () => {
    if (step === 1) {
      if (!useCase) return
      setStep(2)
    } else {
      // Save useCase preference (local or profile settings mock)
      localStorage.setItem('dp_usecase_preference', useCase)
      // Redirect to app
      navigate('/app/analyze')
    }
  }

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex items-center justify-center font-sans p-6">
      {/* Ambient blurs */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden z-0">
        <div className="ambient-glow top-[30%] left-[20%] opacity-10"
          style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 60%)' }} />
      </div>

      <div className="glass max-w-lg w-full p-8 rounded-2xl border border-white/5 relative z-10 space-y-6">
        {/* Step indicator */}
        <div className="flex items-center justify-between text-[10px] text-slate-500 uppercase tracking-widest font-mono">
          <span>Onboarding Progress</span>
          <span>Step {step} of 2</span>
        </div>

        {step === 1 ? (
          <div className="space-y-5 animate-fade-in">
            <div>
              <h2 className="text-base font-bold text-white">Welcome to DataPilot{user?.full_name ? `, ${user.full_name}` : ''}!</h2>
              <p className="text-xs text-slate-400 mt-1">Select your primary use case to customize your dashboard templates.</p>
            </div>

            <div className="grid grid-cols-1 gap-3.5">
              {useCases.map(uc => (
                <button
                  key={uc.id}
                  onClick={() => setUseCase(uc.id)}
                  className={`w-full text-left p-4.5 rounded-xl border text-xs transition-all duration-200 cursor-pointer ${
                    useCase === uc.id
                      ? 'bg-brand-500/10 border-brand-500 text-slate-100 glow-brand-sm'
                      : 'bg-white/5 border-white/5 text-slate-400 hover:border-white/10 hover:text-slate-200'
                  }`}
                >
                  <div className="font-bold">{uc.name}</div>
                  <div className="text-[10px] text-slate-500 mt-1">{uc.desc}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5 animate-fade-in text-center py-4">
            <div className="text-4xl">🚀</div>
            <div>
              <h2 className="text-base font-bold text-white">You're ready to fly!</h2>
              <p className="text-xs text-slate-400 mt-2 max-w-xs mx-auto leading-relaxed">
                We have pre-configured suggested questions and dashboard visualizations tailored to your profile.
              </p>
            </div>

            <div className="glass p-4 rounded-xl text-left border border-white/5 space-y-3.5 max-w-sm mx-auto">
              <h3 className="text-[10px] font-bold uppercase tracking-wider text-brand-300">Your Onboarding Checklist</h3>
              <ul className="text-[11px] text-slate-400 space-y-2 font-medium">
                <li className="flex items-center gap-2">✓ Select a spreadsheet dataset</li>
                <li className="flex items-center gap-2">✓ Ask a conversational question</li>
                <li className="flex items-center gap-2">✓ Compile your first report summary</li>
              </ul>
            </div>
          </div>
        )}

        <button
          onClick={handleNext}
          disabled={step === 1 && !useCase}
          className="btn-primary w-full py-2.5 rounded-xl text-xs font-semibold border-0 disabled:opacity-40"
        >
          {step === 1 ? 'Continue' : 'Enter Workspace'}
        </button>
      </div>
    </div>
  )
}
