import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useDataPilot } from '../hooks/useDataPilot'

const STORAGE_KEY = 'dp_onboarding_state_v1'

export const STARTER_PROMPTS = {
  sales: ['Show monthly sales', 'Top products by profit', 'Worst performing region'],
  finance: ['Find budget variance', 'Forecast revenue', 'Summarize cash flow'],
  hr: ['Show hiring bottlenecks', 'Find missing employee fields', 'Summarize headcount by department'],
  marketing: ['Which campaigns convert best?', 'Find rising cost per lead', 'Create channel performance summary'],
  inventory: ['Find low stock items', 'Show aging inventory', 'Forecast reorder needs'],
  healthcare: ['Find overbooked clinics', 'Show missed appointment trends', 'Summarize capacity risk'],
  construction: ['Which projects are over budget?', 'Find delayed milestones', 'Create project risk summary'],
  operations: ['Find process bottlenecks', 'Show weekly SLA trends', 'Create operations summary'],
}

const defaultState = {
  skipped: false,
  dismissed: false,
  completedCelebrated: false,
}

function readState() {
  try {
    return { ...defaultState, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }
  } catch {
    return defaultState
  }
}

function writeState(next) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)) } catch { /* storage blocked */ }
}

function detectUseCase(files) {
  const name = (files?.[0]?.filename || '').toLowerCase()
  if (/sales|revenue|profit|pipeline/.test(name)) return 'sales'
  if (/finance|budget|expense|cash|ledger/.test(name)) return 'finance'
  if (/employee|hr|hiring|headcount/.test(name)) return 'hr'
  if (/campaign|marketing|lead|channel/.test(name)) return 'marketing'
  if (/inventory|stock|sku|warehouse/.test(name)) return 'inventory'
  if (/clinic|patient|health|appointment/.test(name)) return 'healthcare'
  if (/project|construction|job|milestone/.test(name)) return 'construction'
  return localStorage.getItem('dp_usecase_preference') || 'operations'
}

/**
 * Getting-started checklist shown on the workspace home page (no longer a
 * floating panel that covers the chat composer).  Hidden once dismissed.
 */
export function GettingStarted() {
  const { isGuest, isAuthenticated } = useAuth()
  const { files, datasetsList, messages, reports, historyMessages, setChatPromptInput } = useDataPilot()
  const [state, setState] = useState(readState)

  const useCase = detectUseCase(files)
  const prompts = STARTER_PROMPTS[useCase] || STARTER_PROMPTS.operations
  const hasUpload = files.length > 0 || (datasetsList || []).length > 0
  const hasAnswer = messages.some((m) => m.role !== 'user' && !['loading', 'status', 'error'].includes(m.type)) || historyMessages.length > 0
  const hasChart = messages.some((m) => m.chart_data)
  const hasReport = reports.length > 0 || messages.some((m) => ['report', 'summary'].includes(m.type))
  const hasSaved = reports.length > 0
  const converted = isAuthenticated && (() => { try { return localStorage.getItem('dp_guest_converted_success') === 'true' } catch { return false } })()

  const steps = useMemo(() => [
    { id: 'upload', label: 'Upload a spreadsheet', complete: hasUpload, to: '/app/datasets', tip: 'CSV or Excel, up to 50 MB.' },
    { id: 'ask', label: 'Ask your first question', complete: hasAnswer, to: '/app/analyze', tip: `For example: “${prompts[0]}”` },
    { id: 'chart', label: 'Make a chart', complete: hasChart, to: '/app/analyze', tip: 'Ask for a trend or a comparison.' },
    { id: 'report', label: 'Generate a report', complete: hasReport, to: '/app/reports?view=builder', tip: 'Turn results into a shareable brief.' },
    { id: 'save', label: 'Save a report', complete: hasSaved, to: '/app/saved?view=reports', tip: 'Keep it for later or export it.' },
  ], [hasUpload, hasAnswer, hasChart, hasReport, hasSaved, prompts])

  const done = steps.filter((s) => s.complete).length
  const complete = done === steps.length

  useEffect(() => {
    if (complete && !state.completedCelebrated) {
      const next = { ...state, completedCelebrated: true }
      setState(next)
      writeState(next)
    }
  }, [complete, state])

  if (state.dismissed || (complete && state.completedCelebrated && !converted)) return null

  const dismiss = () => {
    const next = { ...state, dismissed: true }
    setState(next)
    writeState(next)
  }

  return (
    <section className="card" aria-labelledby="getting-started-title">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <div>
          <h2 id="getting-started-title" className="text-md font-semibold text-fg">
            {isGuest ? 'Try Tallis in five steps' : 'Getting started'}
          </h2>
          <p className="mt-0.5 text-sm text-muted">{done} of {steps.length} done</p>
        </div>
        <button type="button" className="btn-ghost btn-sm btn-icon" onClick={dismiss} aria-label="Hide getting started">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {converted && (
        <p className="border-b border-line bg-success-soft px-4 py-2 text-sm text-fg sm:px-5" role="status">
          Your guest work was moved into your new account.
        </p>
      )}
      <div className="h-1 bg-ink/[0.06]" aria-hidden="true">
        <div className="h-full bg-primary transition-[width] duration-base" style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="divide-y divide-line">
        {steps.map((step, i) => (
          <li key={step.id}>
            <Link
              to={step.to}
              state={step.id === 'ask' ? { suggestedPrompt: prompts[0] } : undefined}
              onClick={() => { if (step.id === 'ask') setChatPromptInput(prompts[0]) }}
              className="flex items-center gap-3 px-4 py-2.5 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus sm:px-5"
            >
              <span className={step.complete
                ? 'flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-success text-on-primary'
                : 'flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border border-line-strong text-xs font-medium text-muted'}>
                {step.complete ? <Check className="h-3.5 w-3.5" aria-label="Done" /> : i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className={step.complete ? 'block text-base text-muted line-through decoration-line-strong' : 'block text-base font-medium text-fg'}>{step.label}</span>
                {!step.complete && <span className="block truncate text-sm text-muted">{step.tip}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** Kept for compatibility: the floating assistant is retired in favour of GettingStarted. */
export default function OnboardingAssistant() {
  return null
}
