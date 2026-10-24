import { Link } from 'react-router-dom'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { LogoMark } from '../ui/Logo'

/**
 * Full-page status for transitions (starting a guest workspace, finishing
 * sign-in, loading the session).  Errors always offer a way forward.
 */
export function StatusScreen({ state = 'loading', title, message, actions }) {
  const isError = state === 'error'
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-bg px-4 py-10 text-fg">
      <div className="w-full max-w-sm text-center" role={isError ? 'alert' : 'status'} aria-live="polite">
        <Link to="/" className="mx-auto mb-6 inline-flex rounded-md focus-ring" aria-label="Tallis home">
          <LogoMark size={36} />
        </Link>
        <div className="flex items-center justify-center gap-2">
          {isError
            ? <AlertTriangle className="h-5 w-5 text-danger" aria-hidden="true" />
            : <Loader2 className="h-5 w-5 animate-spin text-primary-text" aria-hidden="true" />}
          <h1 className="text-lg font-semibold">{title}</h1>
        </div>
        {message && <p className="mt-2 text-base text-muted">{message}</p>}
        {actions && <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">{actions}</div>}
      </div>
    </div>
  )
}
