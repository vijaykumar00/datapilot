import { Link } from 'react-router-dom'

const buttonVariants = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  destructive: 'btn-destructive',
}

export function Button({ as: Component = 'button', to, href, variant = 'primary', loading = false, children, className = '', ...props }) {
  const classes = `${buttonVariants[variant] || buttonVariants.primary} ${className}`.trim()
  const content = (
    <>
      {loading && <span className="ui-spinner" aria-hidden="true" />}
      {children}
    </>
  )

  if (to) {
    return (
      <Link to={to} className={classes} aria-disabled={props.disabled ? 'true' : undefined} {...props}>
        {content}
      </Link>
    )
  }

  if (href) {
    return (
      <a href={href} className={classes} {...props}>
        {content}
      </a>
    )
  }

  return (
    <Component className={classes} {...props}>
      {content}
    </Component>
  )
}

export function Card({ className = '', children, ...props }) {
  return (
    <div className={`ui-card ${className}`.trim()} {...props}>
      {children}
    </div>
  )
}

export function Badge({ children, className = '' }) {
  return <span className={`ui-badge ${className}`.trim()}>{children}</span>
}

export function Alert({ title, children, tone = 'info' }) {
  return (
    <div className={`ui-alert ui-alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Input(props) {
  return <input className="input-dark" {...props} />
}

export function Textarea(props) {
  return <textarea className="input-dark min-h-32 resize-y" {...props} />
}

export function EmptyState({ title, description, action }) {
  return (
    <Card className="text-center">
      <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[var(--text-secondary)]">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </Card>
  )
}

export function Skeleton({ className = '' }) {
  return <div className={`ui-skeleton ${className}`.trim()} aria-hidden="true" />
}
