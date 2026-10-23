/**
 * Global toasts (from AuthContext).  Polite live region; errors use role=alert.
 */
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

const META = {
  success: { icon: CheckCircle2, cls: 'text-success' },
  error: { icon: XCircle, cls: 'text-danger' },
  warning: { icon: AlertTriangle, cls: 'text-warning' },
  info: { icon: Info, cls: 'text-info' },
}

function Toast({ id, message, type = 'info', onDismiss }) {
  const meta = META[type] || META.info
  const Icon = meta.icon
  return (
    <div
      className="pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-line bg-elevated px-3.5 py-3 shadow-float animate-slide-up sm:w-[360px]"
      role={type === 'error' ? 'alert' : 'status'}
    >
      <Icon className={`mt-0.5 h-[18px] w-[18px] flex-shrink-0 ${meta.cls}`} aria-hidden="true" />
      <p className="min-w-0 flex-1 text-base text-fg">{message}</p>
      <button
        type="button"
        className="-mr-1 -mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded text-subtle hover:bg-ink/[0.06] hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        onClick={() => onDismiss(id)}
        aria-label="Dismiss notification"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}

function ToastContainer() {
  const { toasts, dismissToast } = useAuth()
  return (
    <div
      className="pb-safe pointer-events-none fixed inset-x-3 bottom-3 z-[70] flex flex-col items-end gap-2 sm:inset-x-auto sm:bottom-5 sm:right-5"
      aria-live="polite"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} {...toast} onDismiss={dismissToast} />
      ))}
    </div>
  )
}

export default ToastContainer
