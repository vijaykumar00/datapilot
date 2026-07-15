/**
 * Global toast notification system.
 * Reads from AuthContext.toasts and renders consistent status messages.
 */
import { useAuth } from '../contexts/AuthContext'

const ICONS = {
  success: 'OK',
  error: '!',
  info: 'i',
  warning: '!',
}

const COLORS = {
  success: 'var(--success)',
  error: 'var(--error)',
  info: 'var(--information)',
  warning: 'var(--warning)',
}

function Toast({ id, message, type = 'info', onDismiss }) {
  const toastType = COLORS[type] ? type : 'info'

  return (
    <div
      className={`toast toast-${toastType}`}
      style={{ '--toast-color': COLORS[toastType] }}
      onClick={() => onDismiss(id)}
      role={toastType === 'error' ? 'alert' : 'status'}
      aria-live="polite"
      tabIndex={0}
    >
      <span className="toast-icon" aria-hidden="true">{ICONS[toastType]}</span>
      <span className="toast-msg">{message}</span>
      <button
        type="button"
        className="toast-close"
        onClick={(event) => {
          event.stopPropagation()
          onDismiss(id)
        }}
        aria-label="Dismiss notification"
      >
        x
      </button>
    </div>
  )
}

function ToastContainer() {
  const { toasts, dismissToast } = useAuth()

  if (!toasts.length) return null

  return (
    <div className="toast-container" aria-label="Notifications">
      {toasts.map((toast) => (
        <Toast key={toast.id} {...toast} onDismiss={dismissToast} />
      ))}
    </div>
  )
}

export default ToastContainer
