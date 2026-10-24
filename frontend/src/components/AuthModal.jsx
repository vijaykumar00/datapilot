/**
 * AuthModal.jsx — sign in, sign up, phone code and password reset.
 *
 * Used as a dialog inside the app (guest → account) and as a full page on
 * /login, /signup and /forgot-password (variant="page").  Social and phone
 * options only appear when the server reports them as configured.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { apiUrl } from '../lib/apiConfig'
import { LogoMark, Wordmark } from './ui/Logo'
import { IconButton, cx } from './ui'

let providersCache = null
export function useAuthProviders() {
  const [providers, setProviders] = useState(providersCache || {})
  useEffect(() => {
    if (providersCache) return undefined
    let cancelled = false
    fetch(apiUrl('/auth/oauth/providers'))
      .then((r) => (r.ok ? r.json() : { providers: [] }))
      .then((data) => {
        const map = {}
        for (const p of data.providers || []) map[p.provider] = !!p.enabled
        providersCache = map
        if (!cancelled) setProviders(map)
      })
      .catch(() => { /* social options stay hidden */ })
    return () => { cancelled = true }
  }, [])
  return providers
}

function Field({ label, hint, optional, children, id }) {
  return (
    <div>
      <label htmlFor={id} className="field-label">
        {label}
        {optional && <span className="ml-1 font-normal text-subtle">(optional)</span>}
      </label>
      {children}
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  )
}

function PasswordInput({ id, value, onChange, show, onToggle, ...rest }) {
  return (
    <div className="relative">
      <input
        id={id}
        type={show ? 'text' : 'password'}
        className="input pr-11"
        value={value}
        onChange={onChange}
        {...rest}
      />
      <button
        type="button"
        onClick={onToggle}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-subtle hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        aria-label={show ? 'Hide password' : 'Show password'}
        aria-pressed={show}
      >
        {show ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
      </button>
    </div>
  )
}

function SubmitButton({ loading, children }) {
  return (
    <button type="submit" className="btn-primary btn-lg w-full" disabled={loading} aria-busy={loading || undefined}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

/** Google's "G" mark, as Google's sign-in branding guidelines ask for on sign-in buttons. */
export function GoogleMark({ className = 'h-[18px] w-[18px]' }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden="true" focusable="false">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  )
}

function SocialButton({ label, mark, onClick, disabled }) {
  return (
    <button type="button" className="btn-secondary btn-lg w-full" onClick={onClick} disabled={disabled}>
      {mark === 'G'
        ? <GoogleMark />
        : <span className="flex h-5 w-5 items-center justify-center rounded border border-line text-xs font-semibold" aria-hidden="true">{mark}</span>}
      {label}
    </button>
  )
}

function AuthModal({ open, onClose, defaultTab = 'login', title = null, variant = 'dialog' }) {
  const {
    login, signup, forgotPassword, convertGuest, beginSocialLogin, requestPhoneOtp, verifyPhoneOtp, isGuest, addToast,
  } = useAuth()
  const providers = useAuthProviders()
  const uid = useId()
  const panelRef = useRef(null)
  const [tab, setTab] = useState(defaultTab)
  const [form, setForm] = useState({
    email: '', password: '', confirmPassword: '', fullName: '', workspaceName: '', phoneNumber: '', otpCode: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [otpSent, setOtpSent] = useState(false)
  const isPage = variant === 'page'

  // Dialog behaviour: focus first field, trap Tab, Escape closes.
  useEffect(() => {
    if (!open) return undefined
    const el = panelRef.current
    if (!el) return undefined
    const selector = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
    const onKey = (e) => {
      if (e.key === 'Escape' && !isPage) { onClose(); return }
      if (e.key === 'Tab' && !isPage) {
        const items = Array.from(el.querySelectorAll(selector))
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault() }
        else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault() }
      }
    }
    window.addEventListener('keydown', onKey)
    const firstInput = el.querySelector('input')
    if (firstInput) firstInput.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, tab, isPage])

  useEffect(() => {
    if (open) {
      setTab(defaultTab)
      setError(''); setSuccess('')
      setOtpSent(false)
    }
  }, [open, defaultTab])

  if (!open) return null

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const selectTab = (nextTab) => {
    setTab(nextTab)
    setError('')
    setSuccess('')
    if (nextTab !== 'phone') setOtpSent(false)
  }

  const run = async (fn) => {
    setError(''); setLoading(true)
    try { await fn() } catch (err) { setError(err.message || 'Something went wrong. Please try again.') } finally { setLoading(false) }
  }

  const handleSocial = async (provider) => {
    setError(''); setLoading(true)
    try { await beginSocialLogin(provider) } catch (err) { setError(err.message); setLoading(false) }
  }

  const handleLogin = (e) => {
    e.preventDefault()
    run(async () => { await login(form.email, form.password); onClose() })
  }

  const handleSignup = (e) => {
    e.preventDefault()
    setError('')
    if (form.password.length < 8) return setError('Use at least 8 characters for your password.')
    if (form.password !== form.confirmPassword) return setError("The two passwords don't match.")
    return run(async () => {
      if (isGuest) {
        await convertGuest(form.email, form.password, form.fullName, form.workspaceName, true)
        localStorage.setItem('dp_guest_converted_success', 'true')
        addToast?.('Account created. Your guest work is saved in this workspace.', 'success')
        onClose()
      } else {
        await signup(form.email, form.password, form.fullName, form.workspaceName)
        setSuccess('Account created. Check your email to verify it, then sign in.')
        setTab('login')
      }
    })
  }

  const handleForgot = (e) => {
    e.preventDefault()
    run(async () => {
      await forgotPassword(form.email)
      setSuccess('If that email has an account, a reset link is on its way.')
    })
  }

  const handlePhoneOtpRequest = (e) => {
    e.preventDefault()
    setSuccess('')
    run(async () => {
      const data = await requestPhoneOtp(form.phoneNumber)
      setOtpSent(true)
      setSuccess(data.dev_otp ? `Development code: ${data.dev_otp}` : 'Code sent. Check your phone.')
    })
  }

  const handlePhoneOtpVerify = (e) => {
    e.preventDefault()
    run(async () => { await verifyPhoneOtp(form.phoneNumber, form.otpCode, form.workspaceName || null); onClose() })
  }

  const hasGoogle = !!providers.google
  const hasMicrosoft = !!providers.microsoft
  // Phone-code sign-in is not part of the MVP; the backend flow stays available.
  const hasPhone = false
  const hasSocial = hasGoogle || hasMicrosoft

  const heading = title || {
    login: 'Sign in to Tallis',
    signup: isGuest ? 'Save your work' : 'Create your account',
    phone: 'Sign in with a phone code',
    forgot: 'Reset your password',
  }[tab]
  const subheading = {
    login: 'Welcome back. Pick up where you left off.',
    signup: isGuest ? 'Your uploads, chats and reports move into your new account.' : 'Free plan, no card required.',
    phone: "We'll text you a one-time code.",
    forgot: "Enter your account email and we'll send a reset link.",
  }[tab]

  const ids = {
    email: `${uid}-email`, password: `${uid}-password`, confirm: `${uid}-confirm`, name: `${uid}-name`,
    workspace: `${uid}-workspace`, phone: `${uid}-phone`, otp: `${uid}-otp`, title: `${uid}-title`,
  }

  const socialBlock = (verb) => (hasSocial || hasPhone) && (
    <div className="space-y-2">
      {hasGoogle && <SocialButton label={`${verb} with Google`} mark="G" onClick={() => handleSocial('google')} disabled={loading} />}
      {hasMicrosoft && <SocialButton label={`${verb} with Microsoft`} mark="M" onClick={() => handleSocial('microsoft')} disabled={loading} />}
      {hasPhone && (
        <button type="button" className="btn-ghost w-full" onClick={() => selectTab('phone')}>Use a phone number instead</button>
      )}
      <div className="flex items-center gap-3 py-1 text-xs text-subtle" role="separator">
        <span className="h-px flex-1 bg-line" />or continue with email<span className="h-px flex-1 bg-line" />
      </div>
    </div>
  )

  const body = (
    <div ref={panelRef} className={cx('w-full', isPage ? 'max-w-[400px]' : '')}>
      {!isPage && (
        <div className="mb-5 flex items-center justify-between">
          <span className="flex items-center gap-2"><LogoMark size={26} /><Wordmark /></span>
          <IconButton icon={X} label="Close" tooltip={false} size="sm" onClick={onClose} />
        </div>
      )}

      <h1 id={ids.title} className="text-2xl font-semibold text-fg">{heading}</h1>
      <p className="mt-1 text-base text-muted">{subheading}</p>

      {(tab === 'login' || tab === 'signup') && (
        <div className="mt-5 grid grid-cols-2 rounded-md border border-line bg-surface-muted p-1" role="tablist" aria-label="Account">
          {['login', 'signup'].map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => selectTab(t)}
              className={cx(
                'h-8 rounded text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
                tab === t ? 'bg-surface text-fg shadow-[0_1px_2px_rgb(0_0_0/0.08)]' : 'text-muted hover:text-fg',
              )}
            >
              {t === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>
      )}

      <div className="mt-5 space-y-4" aria-live="polite">
        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-fg">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div className="flex items-start gap-2 rounded-md border border-success/30 bg-success-soft px-3 py-2.5 text-sm text-fg">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-success" aria-hidden="true" />
            <span>{success}</span>
          </div>
        )}

        {tab === 'login' && (
          <form className="space-y-4" onSubmit={handleLogin} autoComplete="on">
            {socialBlock('Continue')}
            <Field label="Email" id={ids.email}>
              <input id={ids.email} type="email" className="input" autoComplete="email" placeholder="you@company.com"
                value={form.email} onChange={(e) => update('email', e.target.value)} required />
            </Field>
            <div>
              <div className="mb-1.5 flex items-baseline justify-between">
                <label htmlFor={ids.password} className="text-sm font-medium text-fg">Password</label>
                <button type="button" className="text-sm font-medium text-primary-text hover:underline" onClick={() => selectTab('forgot')}>
                  Forgot password?
                </button>
              </div>
              <PasswordInput id={ids.password} autoComplete="current-password" value={form.password}
                onChange={(e) => update('password', e.target.value)} show={showPassword} onToggle={() => setShowPassword((v) => !v)} required />
            </div>
            <SubmitButton loading={loading}>Sign in</SubmitButton>
          </form>
        )}

        {tab === 'signup' && (
          <form className="space-y-4" onSubmit={handleSignup} autoComplete="on">
            {socialBlock('Sign up')}
            <Field label="Full name" id={ids.name} optional>
              <input id={ids.name} type="text" className="input" autoComplete="name" placeholder="Asha Rao"
                value={form.fullName} onChange={(e) => update('fullName', e.target.value)} />
            </Field>
            <Field label="Work email" id={ids.email}>
              <input id={ids.email} type="email" className="input" autoComplete="email" placeholder="you@company.com"
                value={form.email} onChange={(e) => update('email', e.target.value)} required />
            </Field>
            <Field label="Password" id={ids.password} hint="At least 8 characters.">
              <PasswordInput id={ids.password} autoComplete="new-password" minLength={8} value={form.password}
                onChange={(e) => update('password', e.target.value)} show={showPassword} onToggle={() => setShowPassword((v) => !v)} required />
            </Field>
            <Field label="Confirm password" id={ids.confirm}>
              <input id={ids.confirm} type={showPassword ? 'text' : 'password'} className="input" autoComplete="new-password"
                value={form.confirmPassword} onChange={(e) => update('confirmPassword', e.target.value)} required
                aria-invalid={form.confirmPassword && form.confirmPassword !== form.password ? 'true' : undefined} />
            </Field>
            <Field label="Workspace name" id={ids.workspace} optional>
              <input id={ids.workspace} type="text" className="input" placeholder="Finance team"
                value={form.workspaceName} onChange={(e) => update('workspaceName', e.target.value)} />
            </Field>
            <SubmitButton loading={loading}>{isGuest ? 'Create account and keep my work' : 'Create account'}</SubmitButton>
            <p className="text-center text-xs text-subtle">
              By creating an account you agree to the <Link to="/legal/terms" className="underline hover:text-fg">Terms</Link> and{' '}
              <Link to="/legal/privacy" className="underline hover:text-fg">Privacy Policy</Link>.
            </p>
          </form>
        )}

        {tab === 'phone' && (
          <form className="space-y-4" onSubmit={otpSent ? handlePhoneOtpVerify : handlePhoneOtpRequest} autoComplete="on">
            <Field label="Phone number" id={ids.phone} hint="Include your country code, e.g. +15551234567.">
              <input id={ids.phone} type="tel" className="input" autoComplete="tel" placeholder="+15551234567"
                value={form.phoneNumber} onChange={(e) => update('phoneNumber', e.target.value)} required />
            </Field>
            {otpSent && (
              <>
                <Field label="6-digit code" id={ids.otp}>
                  <input id={ids.otp} className="input tracking-[0.3em]" inputMode="numeric" pattern="[0-9]*" autoComplete="one-time-code"
                    value={form.otpCode} onChange={(e) => update('otpCode', e.target.value)} required />
                </Field>
                <Field label="Workspace name" id={ids.workspace} optional>
                  <input id={ids.workspace} type="text" className="input" value={form.workspaceName} onChange={(e) => update('workspaceName', e.target.value)} />
                </Field>
              </>
            )}
            <SubmitButton loading={loading}>{otpSent ? 'Verify code' : 'Send code'}</SubmitButton>
            {otpSent && <button type="button" className="btn-ghost w-full" onClick={handlePhoneOtpRequest} disabled={loading}>Send a new code</button>}
            <button type="button" className="btn-ghost w-full" onClick={() => selectTab('login')}>Sign in with email instead</button>
          </form>
        )}

        {tab === 'forgot' && (
          <form className="space-y-4" onSubmit={handleForgot}>
            <Field label="Email" id={ids.email}>
              <input id={ids.email} type="email" className="input" autoComplete="email" placeholder="you@company.com"
                value={form.email} onChange={(e) => update('email', e.target.value)} required />
            </Field>
            <SubmitButton loading={loading}>Send reset link</SubmitButton>
            <button type="button" className="btn-ghost w-full" onClick={() => selectTab('login')}>Back to sign in</button>
          </form>
        )}
      </div>
    </div>
  )

  if (isPage) {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-bg lg:flex-row">
        <aside className="hidden w-[44%] max-w-[560px] flex-col justify-between border-r border-line bg-surface p-10 lg:flex">
          <Link to="/" className="flex items-center gap-2.5 self-start rounded-md focus-ring" aria-label="Tallis home">
            <LogoMark size={30} /><Wordmark />
          </Link>
          <figure className="max-w-md">
            <blockquote className="text-2xl font-medium leading-snug text-fg">
              Upload a spreadsheet, ask a question in plain English, and get the number — with the SQL that produced it.
            </blockquote>
            <figcaption className="mt-6 space-y-3 text-base text-muted">
              {['Answers are computed from your data, never invented.', 'Every result shows its query and source columns.', 'Files stay private to your workspace.'].map((t) => (
                <p key={t} className="flex items-start gap-2.5"><CheckCircle2 className="mt-1 h-4 w-4 flex-shrink-0 text-success" aria-hidden="true" />{t}</p>
              ))}
            </figcaption>
          </figure>
          <p className="text-sm text-subtle">CSV, XLSX and XLS up to 50 MB.</p>
        </aside>
        <main className="flex flex-1 flex-col">
          <div className="flex h-14 items-center justify-between px-4 sm:px-6 lg:justify-end">
            <Link to="/" className="flex items-center gap-2 rounded-md focus-ring lg:hidden" aria-label="Tallis home">
              <LogoMark size={26} /><Wordmark />
            </Link>
            <Link to="/try-free" className="btn-ghost btn-sm">Try without an account</Link>
          </div>
          <div className="flex flex-1 items-start justify-center px-4 pb-12 pt-6 sm:items-center sm:px-6">
            {body}
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog-panel pb-safe max-w-[440px] overflow-y-auto p-6" role="dialog" aria-modal="true" aria-labelledby={ids.title}>
        {body}
      </div>
    </div>
  )
}

export default AuthModal
