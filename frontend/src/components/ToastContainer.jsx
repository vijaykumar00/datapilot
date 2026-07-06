/**
 * ToastContainer.jsx — Global toast notification system.
 * Reads from AuthContext.toasts and renders them in the bottom-right.
 */
import { useAuth } from '../contexts/AuthContext';

const ICONS = {
  success: '✓',
  error: '✕',
  info: 'ℹ',
  warning: '⚠',
};

const COLORS = {
  success: '#10b981',
  error: '#ef4444',
  info: '#6366f1',
  warning: '#f59e0b',
};

function Toast({ id, message, type, onDismiss }) {
  return (
    <div
      className={`toast toast-${type}`}
      style={{ '--toast-color': COLORS[type] || COLORS.info }}
      onClick={() => onDismiss(id)}
      role="alert"
      aria-live="polite"
    >
      <span className="toast-icon">{ICONS[type] || ICONS.info}</span>
      <span className="toast-msg">{message}</span>
      <button className="toast-close" onClick={() => onDismiss(id)}>✕</button>
    </div>
  );
}

function ToastContainer() {
  const { toasts, dismissToast } = useAuth();

  if (!toasts.length) return null;

  return (
    <div className="toast-container" aria-label="Notifications">
      {toasts.map(t => (
        <Toast key={t.id} {...t} onDismiss={dismissToast} />
      ))}
    </div>
  );
}

export default ToastContainer;
