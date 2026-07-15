import { Link } from 'react-router-dom'

export default function BrandLogo({ compact = false, className = '' }) {
  return (
    <Link
      to="/"
      className={`inline-flex items-center gap-3 rounded-[var(--radius-button)] focus-ring ${className}`}
      aria-label="DataPilot home"
    >
      <img
        src="/assets/logo-mark.svg"
        alt=""
        width="36"
        height="36"
        className="h-9 w-9 flex-none"
        aria-hidden="true"
      />
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-bold tracking-tight text-[var(--text-primary)]">DataPilot</span>
          <span className="mt-1 text-[10px] font-medium text-[var(--text-muted)]">
            SaaS analytics platform
          </span>
        </span>
      )}
    </Link>
  )
}
