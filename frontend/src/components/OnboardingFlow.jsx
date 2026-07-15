import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

const useCases = [
  { id: 'sales', name: 'Sales', desc: 'Revenue trends, products, territories, and pipeline performance.' },
  { id: 'finance', name: 'Finance', desc: 'Budget variance, expenses, cash flow, and forecasts.' },
  { id: 'hr', name: 'HR', desc: 'Headcount, hiring bottlenecks, attrition, and compensation patterns.' },
  { id: 'marketing', name: 'Marketing', desc: 'Campaign ROI, channels, leads, and conversion quality.' },
  { id: 'inventory', name: 'Inventory', desc: 'Stock levels, reorder risk, aging items, and warehouse movement.' },
  { id: 'healthcare', name: 'Healthcare', desc: 'Appointments, utilization, no-shows, and capacity risk.' },
  { id: 'construction', name: 'Construction', desc: 'Project budgets, schedules, milestones, and delivery risk.' },
  { id: 'operations', name: 'Operations', desc: 'SLA trends, bottlenecks, throughput, and process quality.' },
]

const activationSteps = [
  'Upload a spreadsheet',
  'Ask a starter question',
  'Generate a chart',
  'Create a report',
  'Save the report',
]

export default function OnboardingFlow() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [useCase, setUseCase] = useState('')
  const [step, setStep] = useState(1)

  const savePreference = () => {
    const selected = useCase || 'operations'
    localStorage.setItem('dp_usecase_preference', selected)
    localStorage.setItem('dp_onboarding_state_v1', JSON.stringify({
      skipped: false,
      dismissed: false,
      completedCelebrated: false,
    }))
  }

  const handleNext = () => {
    if (step === 1) {
      if (!useCase) return
      setStep(2)
      return
    }
    savePreference()
    navigate('/app/datasets')
  }

  const handleSkip = () => {
    localStorage.setItem('dp_onboarding_state_v1', JSON.stringify({
      skipped: true,
      dismissed: false,
      completedCelebrated: false,
    }))
    navigate('/app')
  }

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex items-center justify-center font-sans p-6">
      <div className="glass max-w-3xl w-full p-6 sm:p-8 rounded-2xl border border-white/5 relative z-10 space-y-6">
        <div className="flex items-center justify-between gap-4 text-[10px] text-slate-500 uppercase tracking-widest font-mono">
          <span>First analysis setup</span>
          <span>Step {step} of 2</span>
        </div>

        {step === 1 ? (
          <div className="space-y-5 animate-fade-in">
            <div>
              <h1 className="text-xl font-bold text-white">Welcome to DataPilot{user?.full_name ? `, ${user.full_name}` : ''}</h1>
              <p className="text-sm text-slate-400 mt-2">
                Pick the spreadsheet type closest to your work. DataPilot will use it to show smarter starter prompts.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {useCases.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setUseCase(item.id)}
                  className={`w-full text-left p-4 rounded-xl border text-sm transition-all duration-200 cursor-pointer ${
                    useCase === item.id
                      ? 'bg-brand-500/10 border-brand-500 text-slate-100 glow-brand-sm'
                      : 'bg-white/5 border-white/5 text-slate-400 hover:border-white/10 hover:text-slate-200'
                  }`}
                >
                  <span className="font-bold block">{item.name}</span>
                  <span className="text-xs text-slate-500 mt-1 block leading-relaxed">{item.desc}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6 animate-fade-in">
            <div>
              <h1 className="text-xl font-bold text-white">Your first win is ready</h1>
              <p className="text-sm text-slate-400 mt-2">
                The workspace assistant will guide you through upload, question, chart, report, and save without a long tutorial.
              </p>
            </div>

            <div className="grid gap-2">
              {activationSteps.map((item, index) => (
                <div key={item} className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.03] px-4 py-3">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-brand-500/15 text-brand-200 text-xs font-bold">
                    {index + 1}
                  </span>
                  <span className="text-sm font-semibold text-slate-200">{item}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-3">
          <button
            type="button"
            onClick={handleNext}
            disabled={step === 1 && !useCase}
            className="btn-primary flex-1 py-3 rounded-xl text-sm font-semibold border-0 disabled:opacity-40"
          >
            {step === 1 ? 'Continue' : 'Start with upload'}
          </button>
          <button
            type="button"
            onClick={handleSkip}
            className="px-4 py-3 rounded-xl border border-white/10 text-sm font-semibold text-slate-300 hover:text-white hover:border-white/20"
          >
            Skip for now
          </button>
        </div>
      </div>
    </div>
  )
}
