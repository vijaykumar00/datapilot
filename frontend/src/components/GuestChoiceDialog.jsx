/**
 * Shown when someone starts Tallis without an account: they choose between a
 * free account (work is saved) and a guest session (work is deleted when the
 * session ends).  Sample data is offered for people who just want to look.
 */
import { useState } from 'react'
import { Clock3, Loader2, ShieldCheck, Table2 } from 'lucide-react'
import Dialog from './ui/Dialog'
import { GoogleMark, useAuthProviders } from './AuthModal'
import { GUEST_CHOICE_KEY, useAuth } from '../contexts/AuthContext'
import { useDataPilot } from '../hooks/useDataPilot'
import { loadSampleData } from '../lib/sampleData'

export function guestChoiceMade() {
  try { return !!sessionStorage.getItem(GUEST_CHOICE_KEY) } catch { return true }
}

function rememberChoice(choice) {
  try { sessionStorage.setItem(GUEST_CHOICE_KEY, choice) } catch { /* storage blocked */ }
}

export default function GuestChoiceDialog({ open, onClose, onSignUp, onSignIn, onSampleLoaded }) {
  const { beginSocialLogin, guestLimits } = useAuth()
  const uploadFile = useDataPilot((s) => s.uploadFile)
  const providers = useAuthProviders()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const hours = guestLimits?.data_deleted_after_hours || 24

  const asGuest = () => { rememberChoice('guest'); onClose() }

  const google = async () => {
    setError(''); setBusy('google')
    try { await beginSocialLogin('google') } catch (err) { setError(err.message); setBusy('') }
  }

  const sample = async () => {
    setError(''); setBusy('sample')
    const result = await loadSampleData(uploadFile)
    setBusy('')
    if (!result?.success) { setError(result?.error || "Couldn't load the sample data. Try again."); return }
    rememberChoice('sample')
    onSampleLoaded?.(result)
    onClose()
  }

  return (
    <Dialog
      open={open}
      onClose={asGuest}
      size="lg"
      title="How do you want to use Tallis?"
      description="Both are free. The difference is whether your work is kept."
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <section className="flex flex-col rounded-lg border border-primary/40 bg-primary-soft/40 p-4" aria-labelledby="choice-account">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary-text" aria-hidden="true" />
            <h3 id="choice-account" className="text-md font-semibold text-fg">Free account</h3>
          </div>
          <p className="mt-2 flex-1 text-sm text-muted">
            Your files, chats and reports are <strong className="font-medium text-fg">saved</strong>. Come back any time,
            from any device.
          </p>
          <div className="mt-4 space-y-2">
            {providers.google && (
              <button type="button" className="btn-secondary w-full" onClick={google} disabled={!!busy} data-autofocus>
                {busy === 'google' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <GoogleMark />}
                Continue with Google
              </button>
            )}
            <button type="button" className="btn-primary w-full" onClick={onSignUp} disabled={!!busy}
              data-autofocus={providers.google ? undefined : true}>
              Sign up with email
            </button>
            <p className="text-center text-sm text-muted">
              Have an account?{' '}
              <button type="button" className="font-medium text-primary-text hover:underline" onClick={onSignIn}>Sign in</button>
            </p>
          </div>
        </section>

        <section className="flex flex-col rounded-lg border border-line bg-surface p-4" aria-labelledby="choice-guest">
          <div className="flex items-center gap-2">
            <Clock3 className="h-5 w-5 text-muted" aria-hidden="true" />
            <h3 id="choice-guest" className="text-md font-semibold text-fg">Guest</h3>
          </div>
          <p className="mt-2 flex-1 text-sm text-muted">
            Nothing is saved. Your files and chats are <strong className="font-medium text-fg">deleted</strong> when you
            end the guest session, or automatically after about {hours} hours.
            {guestLimits?.upload_count ? ` Up to ${guestLimits.upload_count} uploads and ${guestLimits.query_count} questions.` : ''}
          </p>
          <div className="mt-4">
            <button type="button" className="btn-secondary w-full" onClick={asGuest} disabled={!!busy}>
              Continue as guest
            </button>
          </div>
        </section>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface-muted/60 px-4 py-3">
        <p className="text-sm text-muted">Just looking? Explore with a sample sales file — no upload needed.</p>
        <button type="button" className="btn-ghost btn-sm" onClick={sample} disabled={!!busy}>
          {busy === 'sample' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Table2 className="h-4 w-4" aria-hidden="true" />}
          Use sample data
        </button>
      </div>
      {error && <p role="alert" className="field-error mt-3 text-sm">{error}</p>}
    </Dialog>
  )
}
