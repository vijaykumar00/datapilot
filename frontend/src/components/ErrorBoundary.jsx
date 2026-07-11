import React from 'react'

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
      return (
        <div className="min-h-screen bg-[#030712] flex items-center justify-center p-6 text-slate-300 select-none">
          <div className="max-w-md w-full glass-panel p-8 rounded-2xl border border-rose-500/20 bg-slate-900/10 text-center shadow-xl">
            <div className="text-4xl mb-4 select-none animate-pulse">⚠️</div>
            <h2 className="text-base font-bold text-white tracking-tight">Application Interface Crashed</h2>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              An unexpected client-side error occurred inside the rendering layout loop. Your datasets and session state are preserved on the backend.
            </p>
            
            {this.state.error && (
              <div className="bg-[#0d1222] border border-white/5 p-3 rounded-xl mt-5 text-left font-mono text-[10px] text-rose-300 max-h-32 overflow-y-auto custom-scrollbar">
                {this.state.error.toString()}
              </div>
            )}
            
            <button
              onClick={() => window.location.reload()}
              className="mt-6 w-full py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-brand-500/10 transition-all border border-brand-500/25"
            >
              Force Reload Workspace
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
