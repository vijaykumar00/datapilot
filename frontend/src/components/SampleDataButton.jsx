import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Table2 } from 'lucide-react'
import { useDataPilot } from '../hooks/useDataPilot'
import { loadSampleData, SAMPLE_QUESTIONS } from '../lib/sampleData'
import { cx } from './ui'

/** "No file handy? Try sample data" — loads the bundled sales file and opens Ask AI. */
export default function SampleDataButton({ className, variant = 'link', onLoaded }) {
  const uploadFile = useDataPilot((s) => s.uploadFile)
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: false, error: '' })

  const load = async () => {
    setState({ loading: true, error: '' })
    const result = await loadSampleData(uploadFile)
    if (!result?.success) {
      setState({ loading: false, error: result?.error || "Couldn't load the sample data. Try again." })
      return
    }
    setState({ loading: false, error: '' })
    onLoaded?.(result)
    navigate('/app/analyze', { state: { suggestedPrompt: SAMPLE_QUESTIONS[0] } })
  }

  const Icon = state.loading ? Loader2 : Table2
  return (
    <div className={className}>
      <button
        type="button"
        onClick={load}
        disabled={state.loading}
        className={cx(variant === 'link' ? 'btn-ghost btn-sm -ml-2' : 'btn-secondary w-full')}
      >
        <Icon className={cx('h-4 w-4', state.loading && 'animate-spin')} aria-hidden="true" />
        {state.loading ? 'Loading sample data…' : 'Try it with sample sales data'}
      </button>
      {state.error && <p role="alert" className="field-error mt-1 text-sm">{state.error}</p>}
    </div>
  )
}
