import { useEffect, useId, useRef, useState } from 'react'
import { AlertCircle, BarChart3, Bookmark, FileText, Lightbulb, Sparkles, TrendingUp } from 'lucide-react'
import Dialog from './ui/Dialog'
import { Button, cx } from './ui'

const TYPE_OPTIONS = [
  { value: 'insight', label: 'Insight', icon: Lightbulb },
  { value: 'forecast', label: 'Forecast', icon: TrendingUp },
  { value: 'chart', label: 'Chart', icon: BarChart3 },
  { value: 'summary', label: 'Summary', icon: FileText },
  { value: 'clean', label: 'Clean-up', icon: Sparkles },
]

function inferType(msg) {
  const meta = msg?.metadata?.type || msg?.type || ''
  if (meta === 'chart' || msg?.chart_data) return 'chart'
  if (meta === 'forecast') return 'forecast'
  if (meta === 'summary' || meta === 'greeting') return 'summary'
  if (meta === 'clean') return 'clean'
  return 'insight'
}

function autoTitle(query) {
  if (!query) return 'Saved Analysis'
  return query.length > 60 ? query.slice(0, 57) + '…' : query
}

export default function SaveAnalysisModal({ message, onSave, onClose }) {
  const [title, setTitle] = useState(() => autoTitle(message?.userQuery || message?.content || ''))
  const [tags, setTags] = useState('')
  const [type, setType] = useState(() => inferType(message))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [titleError, setTitleError] = useState('')
  const titleRef = useRef(null)
  const ids = { tagsHint: useId(), titleErr: useId(), typeLegend: useId() }

  // The Dialog focuses the title field; also select its text so it is easy to replace.
  useEffect(() => {
    const t = window.setTimeout(() => titleRef.current?.select(), 40)
    return () => window.clearTimeout(t)
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim()) {
      setTitleError('Enter a title so you can find this analysis later.')
      titleRef.current?.focus()
      return
    }
    setSaving(true)
    setError(null)
    try {
      const tagList = tags
        .split(',')
        .map(t => t.trim())
        .filter(Boolean)
      await onSave({ title: title.trim(), type, tags: tagList })
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to save')
      setSaving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      size="sm"
      title="Save analysis"
      description="Keep this answer so you can open it again from Saved analyses."
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            type="submit"
            form="save-analysis-form"
            id="save-analysis-submit"
            icon={Bookmark}
            loading={saving}
          >
            {saving ? 'Saving…' : 'Save analysis'}
          </Button>
        </>
      )}
    >
      <form id="save-analysis-form" onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <div>
          <label htmlFor="save-analysis-title" className="field-label">Title</label>
          <input
            ref={titleRef}
            id="save-analysis-title"
            data-autofocus
            type="text"
            className="input"
            value={title}
            onChange={e => { setTitle(e.target.value); if (titleError) setTitleError('') }}
            maxLength={200}
            required
            placeholder="Give this analysis a name"
            aria-invalid={titleError ? true : undefined}
            aria-describedby={titleError ? ids.titleErr : undefined}
          />
          {titleError && (
            <p id={ids.titleErr} className="field-error" role="alert">
              <AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
              {titleError}
            </p>
          )}
        </div>

        <fieldset>
          <legend id={ids.typeLegend} className="field-label">Type</legend>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-labelledby={ids.typeLegend}>
            {TYPE_OPTIONS.map(opt => {
              const Icon = opt.icon
              const selected = type === opt.value
              return (
                <label
                  key={opt.value}
                  className={cx(
                    'inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-sm font-medium focus-within:ring-2 focus-within:ring-primary/40',
                    selected ? 'border-primary bg-primary-soft text-primary-text' : 'border-line bg-surface text-muted hover:text-fg',
                  )}
                >
                  <input
                    type="radio"
                    name="save-analysis-type"
                    value={opt.value}
                    checked={selected}
                    onChange={() => setType(opt.value)}
                    className="sr-only"
                  />
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {opt.label}
                </label>
              )
            })}
          </div>
        </fieldset>

        <div>
          <label htmlFor="save-analysis-tags" className="field-label">
            Tags <span className="font-normal text-subtle">(optional)</span>
          </label>
          <input
            id="save-analysis-tags"
            type="text"
            className="input"
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="revenue, Q1, forecast"
            aria-describedby={ids.tagsHint}
          />
          <p id={ids.tagsHint} className="field-hint">Separate tags with commas.</p>
        </div>

        {error && (
          <p className="field-error" role="alert">
            <AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
            Could not save this analysis: {error}. Try again.
          </p>
        )}
      </form>
    </Dialog>
  )
}
