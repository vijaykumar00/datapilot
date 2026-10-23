/**
 * DataPilot mark: a heading line climbing across a three-row grid — reads as
 * "data" and "direction" at 16px.  Uses currentColor-free tokens so it works in
 * both themes.
 */
export function LogoMark({ size = 28, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <rect width="32" height="32" rx="7" fill="rgb(var(--c-primary))" />
      <path d="M7 11h18M7 16h18M7 21h18" stroke="rgb(var(--c-on-primary))" strokeOpacity=".28" strokeWidth="1.5" />
      <path d="M7.5 22.5 13 16.5l4 3 7.5-9" fill="none" stroke="rgb(var(--c-on-primary))" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24.5" cy="10.5" r="2.2" fill="rgb(var(--c-on-primary))" />
    </svg>
  )
}

export function Wordmark({ className = '' }) {
  return <span className={`text-md font-semibold text-fg ${className}`}>DataPilot</span>
}
