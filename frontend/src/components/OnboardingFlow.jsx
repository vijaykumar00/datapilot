import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { LogoMark, Wordmark } from './ui/Logo'
import { cx } from './ui'

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
    <div className="flex min-h-[100dvh] flex-col bg-bg text-fg">
      <header className="flex h-14 items-center justify-between px-4 sm:px-6">
        <span className="flex items-center gap-2"><LogoMark size={26} /><Wordmark /></span>
        <span className="text-sm text-muted">First analysis setup · Step {step} of 2</span>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-12 pt-4 sm:items-center sm:px-6">
        <div className="w-full max-w-2xl">
          {step === 1 ? (
            <fieldset>
              <legend className="text-2xl font-semibold text-fg">Welcome to DataPilot{user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}</legend>
              <p className="mt-1 text-base text-muted">What kind of spreadsheets do you work with? We'll suggest questions that fit.</p>
              <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Spreadsheet type">
                {useCases.map((item) => {
                  const selected = useCase === item.id
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setUseCase(item.id)}
                      className={cx(
                        'flex min-h-[64px] items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-ring',
                        selected ? 'border-primary bg-primary-soft' : 'border-line bg-surface hover:border-line-strong',
                      )}
                    >
                      <span className={cx('mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border', selected ? 'border-primary bg-primary' : 'border-line-strong')} aria-hidden="true">
                        {selected && <Check className="h-3 w-3 text-on-primary" />}
                      </span>
                      <span>
                        <span className="block text-base font-medium text-fg">{item.name}</span>
                        <span className="mt-0.5 block text-sm text-muted">{item.desc}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </fieldset>
          ) : (
            <section>
              <h1 className="text-2xl font-semibold text-fg">Here's the plan for your first analysis</h1>
              <p className="mt-1 text-base text-muted">A short checklist on your home page tracks each step.</p>
              <ol className="mt-5 divide-y divide-line rounded-lg border border-line bg-surface">
                {activationSteps.map((item, index) => (
                  <li key={item} className="flex items-center gap-3 px-4 py-3">
                    <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border border-line-strong text-xs font-medium text-muted">{index + 1}</span>
                    <span className="text-base text-fg">{item}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={handleSkip} className="btn-ghost btn-lg">Skip for now</button>
            <button type="button" onClick={handleNext} disabled={step === 1 && !useCase} className="btn-primary btn-lg">
              {step === 1 ? 'Continue' : 'Start with upload'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
