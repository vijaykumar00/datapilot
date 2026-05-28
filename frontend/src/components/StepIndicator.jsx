import { useDataPilot } from '../hooks/useDataPilot'

const STEPS = [
  { id: 'upload', label: 'Upload', icon: '📂', desc: 'Upload a CSV or Excel file' },
  { id: 'sheet',  label: 'Select Sheet', icon: '📋', desc: 'Choose the sheet to analyze' },
  { id: 'ask',    label: 'Ask', icon: '💬', desc: 'Ask a question about your data' },
  { id: 'export', label: 'Export', icon: '📥', desc: 'Download your results' },
]

function getActiveStep(files, messages) {
  if (!files.length) return 'upload'
  const hasMultiSheet = files.some(f => (f.metadata?.sheet_names || []).length > 1)
  if (hasMultiSheet && files.some(f => !f.metadata?.active_sheet)) return 'sheet'
  if (!messages.filter(m => m.role !== 'bot' || m.type !== 'loading').length) return 'ask'
  const hasFinalResult = messages.some(m => m.role !== 'user' && m.table_data?.length > 0)
  if (hasFinalResult) return 'export'
  return 'ask'
}

export default function StepIndicator() {
  const { files, messages } = useDataPilot()
  const currentStep = getActiveStep(files, messages)
  const currentIdx = STEPS.findIndex(s => s.id === currentStep)

  return (
    <div className="px-3 py-2 border-b border-white/5">
      <div className="flex items-center gap-1">
        {STEPS.map((step, idx) => {
          const done = idx < currentIdx
          const active = idx === currentIdx
          return (
            <div key={step.id} className="flex items-center gap-1 flex-1 min-w-0">
              <div
                className={`flex items-center gap-1.5 flex-1 min-w-0 ${active ? '' : ''}`}
                title={step.desc}
              >
                <div
                  className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] flex-shrink-0 transition-all ${
                    done
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                      : active
                        ? 'bg-brand-500/30 text-brand-300 border border-brand-500/60 shadow-sm shadow-brand-500/20'
                        : 'bg-white/5 text-slate-600 border border-white/10'
                  }`}
                >
                  {done ? '✓' : step.icon}
                </div>
                <span
                  className={`text-[10px] truncate hidden sm:block ${
                    active ? 'text-brand-300 font-medium' : done ? 'text-emerald-500' : 'text-slate-600'
                  }`}
                >
                  {step.label}
                </span>
              </div>
              {idx < STEPS.length - 1 && (
                <div className={`h-px w-3 flex-shrink-0 ${done ? 'bg-emerald-500/40' : 'bg-white/10'}`} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
