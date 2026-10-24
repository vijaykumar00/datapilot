import { useCallback, useEffect, useId, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { AlertCircle, Building2, CheckCircle2, CreditCard, Download, Lock, LogOut, ShieldCheck, Trash2, User, UserPlus, Users } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { authedFetch, clearSession, readApiError } from '../lib/authSession'
import Dialog from './ui/Dialog'
import { Badge, Button, EmptyState, ErrorState, IconButton, PageHeader, Skeleton, cx } from './ui'

const NAV_ITEMS = [
  { path: '/app/settings/profile', label: 'Profile', icon: User },
  { path: '/app/settings/workspace', label: 'Workspace', icon: Building2 },
  { path: '/app/settings/members', label: 'Team members', icon: Users },
  { path: '/app/settings/security', label: 'Password and security', icon: ShieldCheck },
  { path: '/app/settings/privacy', label: 'Privacy and data', icon: Lock },
  { path: '/app/settings/billing', label: 'Billing and usage', icon: CreditCard },
]

export default function SettingsLayout() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6 lg:py-8">
      <PageHeader title="Settings" description="Manage your profile, workspace, team and billing." />

      <div className="flex min-w-0 flex-col gap-5 lg:flex-row lg:items-start lg:gap-8">
        {/* Mobile/tablet: horizontally scrollable tab row. Desktop: vertical side nav. */}
        <nav aria-label="Settings sections" className="-mx-4 min-w-0 border-b border-line sm:-mx-6 lg:mx-0 lg:w-56 lg:flex-shrink-0 lg:border-b-0">
          <ul className="flex gap-1 overflow-x-auto px-4 sm:px-6 lg:flex-col lg:gap-0.5 lg:overflow-visible lg:px-0">
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
              <li key={path} className="flex-shrink-0">
                <NavLink
                  to={path}
                  className={({ isActive }) => cx(
                    'flex h-10 items-center gap-2 whitespace-nowrap text-base font-medium transition-colors duration-fast focus-ring',
                    'border-b-2 px-2.5 lg:h-9 lg:rounded-md lg:border-b-0',
                    isActive
                      ? 'border-primary text-fg lg:bg-primary-soft lg:text-primary-text'
                      : 'border-transparent text-muted hover:text-fg lg:hover:bg-surface-muted',
                  )}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

// ── Shared form helpers ──────────────────────────────────────────────────────

function SectionHeading({ title, description }) {
  return (
    <div className="mb-5">
      <h2 className="text-lg font-semibold text-fg">{title}</h2>
      {description && <p className="mt-1 text-sm text-muted">{description}</p>}
    </div>
  )
}

function FieldError({ id, children }) {
  if (!children) return null
  return (
    <p id={id} className="field-error" role="alert">
      <AlertCircle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

function SaveFeedback({ saved, message = 'Changes saved.' }) {
  return (
    <p role="status" aria-live="polite" className="flex min-h-[20px] items-center gap-1.5 text-sm text-success">
      {saved && (
        <>
          <CheckCircle2 className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
          {message}
        </>
      )}
    </p>
  )
}

function FormError({ children }) {
  if (!children) return null
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-fg">
      <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden="true" />
      <span>{children}</span>
    </div>
  )
}

// ── Shared API helper ────────────────────────────────────────────────────────

async function api(path, { method = 'GET', body } = {}) {
  const resp = await authedFetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) throw new Error(await readApiError(resp, 'Something went wrong'))
  return resp.status === 204 ? null : resp.json()
}

/** Settings that need an account show this to guest users. */
function GuestNotice({ what }) {
  return (
    <section className="card">
      <EmptyState
        icon={User}
        title="Create a free account first"
        description={`${what} are available once you have an account. Your guest work moves into it.`}
        action={<Link to="/signup" className="btn-primary">Create free account</Link>}
      />
    </section>
  )
}

function useSavedFlag() {
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    if (!saved) return undefined
    const t = window.setTimeout(() => setSaved(false), 2500)
    return () => window.clearTimeout(t)
  }, [saved])
  return [saved, setSaved]
}

// ── Profile ──────────────────────────────────────────────────────────────────

export function ProfileSettings() {
  const { user, isAuthenticated, updateUser } = useAuth()
  const [name, setName] = useState(user?.full_name || '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useSavedFlag()
  const [nameError, setNameError] = useState('')
  const [formError, setFormError] = useState('')

  if (!isAuthenticated) return <GuestNotice what="Profile settings" />

  const handleSave = async (e) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) { setNameError('Enter your full name.'); return }
    setNameError('')
    setFormError('')
    setSaving(true)
    try {
      await api('/user/profile', { method: 'PUT', body: { full_name: trimmed } })
      updateUser?.({ full_name: trimmed })
      setSaved(true)
    } catch (err) {
      setFormError(`Your name wasn't saved. ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card card-pad max-w-xl">
      <SectionHeading title="Profile" description="How your name appears to your team." />
      <form onSubmit={handleSave} noValidate className="space-y-4">
        <FormError>{formError}</FormError>
        <div>
          <label htmlFor="settings-full-name" className="field-label">Full name</label>
          <input
            id="settings-full-name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(e) => { setName(e.target.value); if (nameError) setNameError('') }}
            aria-invalid={nameError ? 'true' : undefined}
            aria-describedby={nameError ? 'settings-full-name-error' : undefined}
            className="input"
          />
          <FieldError id="settings-full-name-error">{nameError}</FieldError>
        </div>
        <div>
          <label htmlFor="settings-email" className="field-label">Email address</label>
          <input id="settings-email" type="email" value={user?.email || ''} readOnly aria-describedby="settings-email-hint" className="input cursor-not-allowed bg-surface-muted text-muted" />
          <p id="settings-email-hint" className="field-hint">Your sign-in email can't be changed here.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button type="submit" variant="primary" loading={saving}>Save profile</Button>
          <SaveFeedback saved={saved} message="Profile saved." />
        </div>
      </form>
    </section>
  )
}

// ── Workspace ────────────────────────────────────────────────────────────────

function useWorkspace() {
  const { workspaceId, isAuthenticated } = useAuth()
  const [state, setState] = useState({ loading: true, error: '', workspace: null })
  const load = useCallback(async () => {
    if (!isAuthenticated || !workspaceId) { setState({ loading: false, error: '', workspace: null }); return }
    setState((s) => ({ ...s, loading: true, error: '' }))
    try {
      const data = await api(`/workspaces/${encodeURIComponent(workspaceId)}`)
      setState({ loading: false, error: '', workspace: data.workspace })
    } catch (err) {
      setState({ loading: false, error: err.message, workspace: null })
    }
  }, [workspaceId, isAuthenticated])
  useEffect(() => { load() }, [load])
  return { ...state, reload: load, workspaceId, setWorkspace: (workspace) => setState((s) => ({ ...s, workspace })) }
}

const canManage = (role) => role === 'Owner' || role === 'Admin'

export function WorkspaceSettings() {
  const { isAuthenticated } = useAuth()
  const { loading, error, workspace, reload, workspaceId, setWorkspace } = useWorkspace()
  const [wsName, setWsName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useSavedFlag()
  const [nameError, setNameError] = useState('')
  const [formError, setFormError] = useState('')

  useEffect(() => { if (workspace) setWsName(workspace.name || '') }, [workspace])

  if (!isAuthenticated) return <GuestNotice what="Workspace settings" />
  if (loading) return <section className="card card-pad max-w-xl space-y-3"><Skeleton className="h-5 w-32" /><Skeleton className="h-10 w-full" /></section>
  if (error) return <ErrorState title="Couldn't load your workspace" description={error} onRetry={reload} />
  if (!workspace) return null

  const editable = canManage(workspace.your_role)

  const handleSave = async (e) => {
    e.preventDefault()
    const trimmed = wsName.trim()
    if (!trimmed) { setNameError('Enter a workspace name.'); return }
    setNameError('')
    setFormError('')
    setSaving(true)
    try {
      const data = await api(`/workspaces/${encodeURIComponent(workspaceId)}`, { method: 'PUT', body: { name: trimmed } })
      setWorkspace(data.workspace || { ...workspace, name: trimmed })
      setSaved(true)
    } catch (err) {
      setFormError(`The workspace name wasn't saved. ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card card-pad max-w-xl">
      <SectionHeading title="Workspace" description="Everyone in this workspace shares its datasets, chats and reports." />
      <form onSubmit={handleSave} noValidate className="space-y-4">
        <FormError>{formError}</FormError>
        <div>
          <label htmlFor="settings-ws-name" className="field-label">Workspace name</label>
          <input
            id="settings-ws-name"
            type="text"
            value={wsName}
            disabled={!editable}
            onChange={(e) => { setWsName(e.target.value); if (nameError) setNameError('') }}
            aria-invalid={nameError ? 'true' : undefined}
            aria-describedby={cx(nameError && 'settings-ws-name-error', !editable && 'settings-ws-name-hint')}
            className="input"
          />
          {!editable && <p id="settings-ws-name-hint" className="field-hint">Only owners and admins can rename the workspace.</p>}
          <FieldError id="settings-ws-name-error">{nameError}</FieldError>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-base">
          <dt className="text-muted">Your role</dt><dd className="text-fg">{workspace.your_role}</dd>
          <dt className="text-muted">Plan</dt><dd className="capitalize text-fg">{workspace.plan_tier || 'free'}</dd>
        </dl>
        {editable && (
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button type="submit" variant="primary" loading={saving}>Save workspace</Button>
            <SaveFeedback saved={saved} message="Workspace saved." />
          </div>
        )}
      </form>
    </section>
  )
}

// ── Team members ─────────────────────────────────────────────────────────────

const ROLE_HELP = {
  Admin: 'Can invite people and change settings',
  Member: 'Can upload data, ask questions and build reports',
  Viewer: 'Can view datasets, chats and reports',
}

export function TeamMembersSettings() {
  const { user, isAuthenticated } = useAuth()
  const { workspace, workspaceId, loading: wsLoading } = useWorkspace()
  const [members, setMembers] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('Member')
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyId, setBusyId] = useState(null)
  const ids = { email: useId(), role: useId() }

  const load = useCallback(async () => {
    if (!isAuthenticated || !workspaceId) return
    setLoadError('')
    try {
      const data = await api(`/workspaces/${encodeURIComponent(workspaceId)}/members`)
      setMembers(data.members || [])
    } catch (err) {
      setLoadError(err.message)
    }
  }, [isAuthenticated, workspaceId])
  useEffect(() => { load() }, [load])

  if (!isAuthenticated) return <GuestNotice what="Team members" />

  const manage = canManage(workspace?.your_role)

  const invite = async (e) => {
    e.preventDefault()
    const value = email.trim()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) { setInviteError('Enter a valid email address, like name@company.com.'); return }
    setInviteError('')
    setNotice('')
    setInviting(true)
    try {
      await api(`/workspaces/${encodeURIComponent(workspaceId)}/members`, { method: 'POST', body: { email: value, role } })
      setEmail('')
      setNotice(`${value} was added as ${role}.`)
      load()
    } catch (err) {
      setInviteError(err.message)
    } finally {
      setInviting(false)
    }
  }

  const remove = async (m) => {
    if (!window.confirm(`Remove ${m.email} from this workspace? They will lose access immediately.`)) return
    setBusyId(m.user_id)
    setNotice('')
    try {
      await api(`/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(m.user_id)}`, { method: 'DELETE' })
      setNotice(`${m.email} was removed.`)
      load()
    } catch (err) {
      setLoadError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="max-w-3xl space-y-5">
      <SectionHeading title="Team members" description="People who can use this workspace." />

      {manage && (
        <form onSubmit={invite} noValidate className="card card-pad space-y-3">
          <h3 className="text-md font-semibold text-fg">Add a person</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_180px_auto] sm:items-start">
            <div>
              <label htmlFor={ids.email} className="field-label">Email</label>
              <input id={ids.email} type="email" className="input" placeholder="name@company.com" value={email}
                onChange={(e) => { setEmail(e.target.value); if (inviteError) setInviteError('') }}
                aria-invalid={inviteError ? 'true' : undefined} aria-describedby={inviteError ? `${ids.email}-err` : undefined} />
            </div>
            <div>
              <label htmlFor={ids.role} className="field-label">Role</label>
              <select id={ids.role} className="input" value={role} onChange={(e) => setRole(e.target.value)} aria-describedby={`${ids.role}-hint`}>
                {Object.keys(ROLE_HELP).map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div className="sm:pt-[26px]">
              <Button type="submit" variant="primary" icon={UserPlus} loading={inviting} className="w-full sm:w-auto">Add</Button>
            </div>
          </div>
          <p id={`${ids.role}-hint`} className="field-hint">{ROLE_HELP[role]}. The person needs a Tallis account with this email.</p>
          <FieldError id={`${ids.email}-err`}>{inviteError}</FieldError>
        </form>
      )}

      {notice && <SaveFeedback saved message={notice} />}

      <div className="card overflow-hidden">
        {loadError ? (
          <div className="p-4"><ErrorState title="Couldn't load team members" description={loadError} onRetry={load} /></div>
        ) : members === null || wsLoading ? (
          <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
        ) : members.length === 0 ? (
          <EmptyState compact icon={Users} title="Just you so far" description="Add teammates to share datasets and reports." />
        ) : (
          <ul className="divide-y divide-line">
            {members.map((m) => {
              const isYou = m.user_id === user?.user_id || m.email === user?.email
              return (
                <li key={m.user_id || m.email} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary-text" aria-hidden="true">
                    {(m.full_name || m.email || '?')[0].toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-base font-medium text-fg">{m.full_name || m.email}{isYou && <span className="font-normal text-muted"> (you)</span>}</p>
                    {m.full_name && <p className="truncate text-sm text-muted">{m.email}</p>}
                  </div>
                  <Badge tone={m.role === 'Owner' ? 'primary' : 'neutral'}>{m.role}</Badge>
                  {manage && !isYou && m.role !== 'Owner' && (
                    <IconButton icon={Trash2} label={`Remove ${m.email}`} tooltipSide="left" className="hover:text-danger" disabled={busyId === m.user_id} onClick={() => remove(m)} />
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

// ── Password and security ────────────────────────────────────────────────────

export function SecuritySessionsSettings() {
  const { isAuthenticated, logout } = useAuth()
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useSavedFlag()

  if (!isAuthenticated) return <GuestNotice what="Password settings" />

  const set = (k) => (e) => { setForm((f) => ({ ...f, [k]: e.target.value })); if (errors[k]) setErrors((x) => ({ ...x, [k]: undefined })) }

  const submit = async (e) => {
    e.preventDefault()
    const next = {}
    if (!form.current) next.current = 'Enter your current password.'
    if (form.next.length < 8) next.next = 'Use at least 8 characters.'
    if (form.confirm !== form.next) next.confirm = "The two new passwords don't match."
    setErrors(next)
    if (Object.keys(next).length) return
    setFormError('')
    setSaving(true)
    try {
      await api('/user/password', { method: 'PUT', body: { current_password: form.current, new_password: form.next } })
      setForm({ current: '', next: '', confirm: '' })
      setSaved(true)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const field = (key, label, autoComplete, hint) => (
    <div>
      <label htmlFor={`pw-${key}`} className="field-label">{label}</label>
      <input id={`pw-${key}`} type="password" autoComplete={autoComplete} className="input" value={form[key]} onChange={set(key)}
        aria-invalid={errors[key] ? 'true' : undefined} aria-describedby={cx(hint && `pw-${key}-hint`, errors[key] && `pw-${key}-err`)} />
      {hint && <p id={`pw-${key}-hint`} className="field-hint">{hint}</p>}
      <FieldError id={`pw-${key}-err`}>{errors[key]}</FieldError>
    </div>
  )

  return (
    <div className="max-w-xl space-y-5">
      <section className="card card-pad">
        <SectionHeading title="Change password" description="Changing your password signs you out on every other device." />
        <form onSubmit={submit} noValidate className="space-y-4">
          <FormError>{formError}</FormError>
          {field('current', 'Current password', 'current-password')}
          {field('next', 'New password', 'new-password', 'At least 8 characters.')}
          {field('confirm', 'Confirm new password', 'new-password')}
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button type="submit" variant="primary" loading={saving}>Update password</Button>
            <SaveFeedback saved={saved} message="Password updated." />
          </div>
        </form>
      </section>
      <section className="card card-pad">
        <SectionHeading title="Sign out" description="Sign out of Tallis on this device." />
        <Button icon={LogOut} onClick={logout}>Sign out</Button>
      </section>
    </div>
  )
}

// ── Privacy and data ─────────────────────────────────────────────────────────

const PRIVACY_POINTS = [
  'Your files stay in your workspace. We never sell them or use them to train AI models.',
  'Answers marked “Answered instantly” or “Reused query” are calculated on Tallis servers. Nothing is sent to an AI service.',
  'When a question needs AI, the AI service receives your question, the column names and a few sample rows or summary figures — never the whole file. On upload, column names and a few sample values may be sent so Tallis understands your columns.',
  'Delete any file at any time. Deleting your account deletes everything you own here.',
]

async function waitForJob(jobId, tries = 120) {
  for (let i = 0; i < tries; i += 1) {
    const job = await api(`/jobs/${encodeURIComponent(jobId)}`)
    if (job.status === 'succeeded') return job
    if (job.status === 'failed' || job.status === 'dead') throw new Error(job.error || 'The export failed. Try again.')
    await new Promise((r) => window.setTimeout(r, 1000))
  }
  throw new Error('The export is taking longer than expected. Try again in a minute.')
}

export function PrivacySettings() {
  const { isAuthenticated, user } = useAuth()
  const { loading, error, workspace, reload, workspaceId, setWorkspace } = useWorkspace()
  const [aiSaving, setAiSaving] = useState(false)
  const [aiError, setAiError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)

  if (!isAuthenticated) return <GuestNotice what="Privacy settings" />
  if (loading) return <section className="card card-pad max-w-xl space-y-3"><Skeleton className="h-5 w-32" /><Skeleton className="h-10 w-full" /></section>
  if (error) return <ErrorState title="Couldn't load your workspace" description={error} onRetry={reload} />
  if (!workspace) return null

  const editable = canManage(workspace.your_role)
  const aiOn = workspace.ai_enabled !== false

  const toggleAi = async () => {
    setAiError(''); setAiSaving(true)
    try {
      const data = await api(`/workspaces/${encodeURIComponent(workspaceId)}`, { method: 'PUT', body: { ai_enabled: !aiOn } })
      setWorkspace(data.workspace || { ...workspace, ai_enabled: !aiOn })
    } catch (err) {
      setAiError(err.message)
    } finally {
      setAiSaving(false)
    }
  }

  const exportData = async () => {
    setExportError(''); setExporting(true)
    try {
      const { job_id: jobId } = await api('/user/export', { method: 'POST' })
      const job = await waitForJob(jobId)
      const resp = await authedFetch(`/jobs/${encodeURIComponent(jobId)}/download`)
      if (!resp.ok) throw new Error(await readApiError(resp, "The export couldn't be downloaded."))
      const url = URL.createObjectURL(await resp.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = job.result?.filename || 'tallis-export.zip'
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 5000)
    } catch (err) {
      setExportError(err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <section className="card card-pad">
        <SectionHeading title="How your data is handled" />
        <ul className="space-y-2.5">
          {PRIVACY_POINTS.map((point) => (
            <li key={point} className="flex gap-2.5 text-base text-fg">
              <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-success" aria-hidden="true" />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 id="ai-switch-label" className="text-lg font-semibold text-fg">Use AI for questions</h2>
            <p id="ai-switch-desc" className="mt-1 text-sm text-muted">
              {aiOn
                ? 'On: questions the built-in engine can’t answer go to an AI service, as described above.'
                : 'Off: nothing from this workspace is ever sent to an AI service. Tallis answers direct questions with its built-in engine; questions that need AI are declined.'}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={aiOn}
            aria-labelledby="ai-switch-label"
            aria-describedby="ai-switch-desc"
            disabled={!editable || aiSaving}
            onClick={toggleAi}
            className={cx(
              'relative inline-flex h-7 w-12 flex-shrink-0 items-center rounded-full transition-colors duration-fast focus-ring disabled:opacity-60',
              aiOn ? 'bg-primary' : 'bg-ink/20',
            )}
          >
            <span className={cx('inline-block h-5 w-5 rounded-full bg-surface shadow transition-transform duration-fast', aiOn ? 'translate-x-6' : 'translate-x-1')} />
          </button>
        </div>
        {!editable && <p className="field-hint mt-3">Only workspace owners and admins can change this.</p>}
        {aiError && <div className="mt-3"><FormError>{aiError}</FormError></div>}
      </section>

      <section className="card card-pad">
        <SectionHeading
          title="Download your data"
          description="A .zip with your profile, every file in this workspace as CSV, your chats, saved answers and reports."
        />
        <FormError>{exportError}</FormError>
        <Button icon={Download} onClick={exportData} loading={exporting} className={exportError ? 'mt-3' : ''}>
          {exporting ? 'Preparing your download…' : 'Download my data'}
        </Button>
      </section>

      <section className="card card-pad border-danger/30">
        <SectionHeading
          title="Delete account"
          description="Permanently deletes your account, the workspaces you own (with their files, chats and reports) and your chats elsewhere. This can't be undone."
        />
        <Button variant="danger" icon={Trash2} onClick={() => setDeleteOpen(true)}>Delete my account</Button>
      </section>

      <DeleteAccountDialog open={deleteOpen} onClose={() => setDeleteOpen(false)} email={user?.email || ''} />
    </div>
  )
}

function DeleteAccountDialog({ open, onClose, email }) {
  const [confirmEmail, setConfirmEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const matches = confirmEmail.trim().toLowerCase() === email.toLowerCase() && !!email

  const submit = async (e) => {
    e.preventDefault()
    if (!matches) { setError('Type your account email exactly to confirm.'); return }
    setError(''); setBusy(true)
    try {
      await api('/user/account', { method: 'DELETE', body: { confirm_email: confirmEmail.trim(), password: password || null } })
      clearSession()
      try { localStorage.removeItem('datapilot_session_id') } catch { /* storage blocked */ }
      window.location.replace('/')
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => { if (!busy) onClose() }}
      size="sm"
      title="Delete your account?"
      description="Everything you own in Tallis is deleted for good. Download your data first if you want a copy."
    >
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError>{error}</FormError>
        <div>
          <label htmlFor="delete-email" className="field-label">Type <span className="font-semibold">{email}</span> to confirm</label>
          <input id="delete-email" type="email" autoComplete="off" className="input" value={confirmEmail}
            onChange={(e) => setConfirmEmail(e.target.value)} data-autofocus />
        </div>
        <div>
          <label htmlFor="delete-password" className="field-label">Password</label>
          <input id="delete-password" type="password" autoComplete="current-password" className="input" value={password}
            onChange={(e) => setPassword(e.target.value)} aria-describedby="delete-password-hint" />
          <p id="delete-password-hint" className="field-hint">Not needed if you only sign in with Google.</p>
        </div>
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <Button type="button" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="danger" icon={Trash2} loading={busy} disabled={!matches}>Delete account</Button>
        </div>
      </form>
    </Dialog>
  )
}
