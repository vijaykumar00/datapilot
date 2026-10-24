/**
 * Tallis mark: a tally of five (four strokes crossed by a fifth) — counting,
 * the thing the product does for you.  Reads clearly at 16px and uses theme
 * tokens so it works in light and dark.
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
      <path d="M10.5 9.5v13M14.5 9.5v13M18.5 9.5v13M22.5 9.5v13" stroke="rgb(var(--c-on-primary))" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M7.5 20 25 12" stroke="rgb(var(--c-on-primary))" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}

export function Wordmark({ className = '' }) {
  return <span className={`text-md font-semibold text-fg ${className}`}>Tallis</span>
}
