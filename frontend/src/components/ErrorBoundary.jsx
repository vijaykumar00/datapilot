import React from 'react'
import { AlertTriangle, Home, RotateCw } from 'lucide-react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo })
    console.error("ErrorBoundary caught an unhandled React crash:", error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      // This boundary may sit outside the router, so navigation uses plain URLs.
      return (
        <div className="flex min-h-screen w-full items-center justify-center bg-bg px-4 py-10 text-fg">
          <div role="alert" className="card w-full max-w-md p-6 text-center sm:p-8">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-surface-muted text-warning">
              <AlertTriangle className="h-5 w-5" aria-hidden="true" />
            </div>
            <h1 className="mt-4 text-xl font-semibold text-fg">Something went wrong on this page</h1>
            <p className="mt-2 text-base leading-relaxed text-muted">
              The page stopped working because of an unexpected problem. Your files and saved work are safe.
              Reload the page to try again, or go back to the home screen.
            </p>
            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
              <button type="button" onClick={() => window.location.reload()} className="btn-primary">
                <RotateCw className="h-4 w-4" aria-hidden="true" />
                Reload page
              </button>
              <a href="/" className="btn-secondary">
                <Home className="h-4 w-4" aria-hidden="true" />
                Go to home
              </a>
            </div>
            <p className="mt-5 text-sm text-subtle">If this keeps happening, contact support and tell us what you were doing.</p>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
