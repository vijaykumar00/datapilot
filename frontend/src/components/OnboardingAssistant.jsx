import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
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
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
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

export default function OnboardingAssistant() {
  const location = useLocation()
  const { isGuest, isAuthenticated } = useAuth()
  const { files, messages, reports, historyMessages, setChatPromptInput } = useDataPilot()
  const [state, setState] = useState(readState)
  const [expanded, setExpanded] = useState(false)

  const useCase = detectUseCase(files)
  const prompts = STARTER_PROMPTS[useCase] || STARTER_PROMPTS.operations
  const hasUpload = files.length > 0
  const hasAnswer = messages.some((message) => message.role === 'assistant' && message.type !== 'loading' && message.type !== 'status') || historyMessages.length > 0
  const hasChart = messages.some((message) => message.chart_data)
  const hasReport = reports.length > 0 || messages.some((message) => ['report', 'summary'].includes(message.type))
  const hasSaved = reports.length > 0
  const converted = isAuthenticated && localStorage.getItem('dp_guest_converted_success') === 'true'

  const steps = useMemo(() => [
    { id: 'upload', label: 'Upload spreadsheet', complete: hasUpload, to: '/app/datasets', tip: 'Upload your first spreadsheet.' },
    { id: 'ask', label: 'Ask first question', complete: hasAnswer, to: '/app/analyze', tip: `Try asking: ${prompts[0]}` },
    { id: 'chart', label: 'Generate chart', complete: hasChart, to: '/app/analyze', tip: 'Ask for a chart or trend visualization.' },
    { id: 'report', label: 'Generate report', complete: hasReport, to: '/app/report', tip: 'Generate your first executive report.' },
    { id: 'save', label: 'Save report', complete: hasSaved, to: '/app/reports', tip: 'Save or export the result for later review.' },
  ], [hasUpload, hasAnswer, hasChart, hasReport, hasSaved, prompts])

  const completeCount = steps.filter((step) => step.complete).length
  const complete = completeCount === steps.length
  const nextStep = steps.find((step) => !step.complete) || steps[steps.length - 1]
  const progress = Math.round((completeCount / steps.length) * 100)

  useEffect(() => {
    if (!complete || state.completedCelebrated) return
    const next = { ...state, completedCelebrated: true }
    setState(next)
    writeState(next)
    setExpanded(true)
  }, [complete, state])

  useEffect(() => {
    if (state.dismissed || state.skipped) return
    setExpanded(false)
  }, [location.pathname])

  if (state.dismissed) return null

  const persist = (patch) => {
    const next = { ...state, ...patch }
    setState(next)
    writeState(next)
  }

  const applyPrompt = (prompt) => {
    setChatPromptInput(prompt)
  }

  return (
    <aside className={`onboarding-assistant ${expanded ? 'is-expanded' : ''}`} aria-label="Guided onboarding">
      <button
        type="button"
        className="onboarding-assistant-toggle"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span>{complete ? 'Onboarding complete' : state.skipped ? 'Onboarding paused' : nextStep.tip}</span>
        <strong>{progress}%</strong>
      </button>

      {expanded && (
        <div className="onboarding-panel">
          <div className="onboarding-panel-header">
            <div>
              <span>{isGuest ? 'Guest activation' : 'Workspace activation'}</span>
              <h2>{complete ? 'You did it. DataPilot is ready.' : 'Your first successful analysis'}</h2>
            </div>
            <button type="button" onClick={() => persist({ dismissed: true })} aria-label="Dismiss onboarding">
              Close
            </button>
          </div>

          {converted && (
            <div className="onboarding-success" role="status">
              Guest converted to account. Your work is preserved and the workspace is open.
            </div>
          )}

          {complete && (
            <div className="onboarding-celebration" role="status">
              Success: you uploaded data, asked a question, generated insight, and reached a saved report workflow.
            </div>
          )}

          <div className="onboarding-progress-track" aria-label={`Onboarding ${progress}% complete`}>
            <i style={{ width: `${progress}%` }} />
          </div>

          <div className="onboarding-step-list">
            {steps.map((step, index) => (
              <Link key={step.id} to={step.to} className={step.complete ? 'is-complete' : step.id === nextStep.id ? 'is-next' : ''}>
                <span>{step.complete ? 'Done' : index + 1}</span>
                <div>
                  <strong>{step.label}</strong>
                  <small>{step.complete ? 'Completed' : step.tip}</small>
                </div>
              </Link>
            ))}
          </div>

          <div className="onboarding-prompt-box">
            <strong>Smart starter prompts for {useCase}</strong>
            <div>
              {prompts.map((prompt) => (
                <Link key={prompt} to="/app/analyze" state={{ suggestedPrompt: prompt }} onClick={() => applyPrompt(prompt)}>
                  {prompt}
                </Link>
              ))}
            </div>
          </div>

          <div className="onboarding-panel-actions">
            {state.skipped ? (
              <button type="button" onClick={() => persist({ skipped: false, dismissed: false })}>Resume onboarding</button>
            ) : (
              <button type="button" onClick={() => persist({ skipped: true })}>Skip onboarding</button>
            )}
            <button type="button" onClick={() => setExpanded(false)}>Resume later</button>
          </div>
        </div>
      )}
    </aside>
  )
}
