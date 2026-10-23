import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AlertCircle, AlertTriangle, ArrowUpRight, Check, CheckCircle2, Info, RefreshCw, XCircle } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import {
  BillingApiError,
  centsToPrice,
  createBillingClient,
  daysUntil,
  formatBytes,
  formatLimit,
  friendlyBillingStatus,
  isSafeBillingRedirect,
} from '../lib/billingClient'
import { Badge, Button, Skeleton, cx } from './ui'

const METRICS = [
  ['ai_prompt_count', 'AI prompts'],
  ['query_count', 'Analytics queries'],
  ['upload_count', 'Uploads'],
  ['dataset_count', 'Datasets'],
  ['report_count', 'Reports'],
  ['export_count', 'Exports'],
  ['storage_bytes', 'Storage', 'bytes'],
  ['chart_count', 'Charts'],
  ['member_count', 'Workspace members'],
  ['api_usage_count', 'API usage'],
]

function formatDate(value) {
  if (!value) return 'Not set'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Not set'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function planPrice(plan, interval) {
  if (plan?.plan_id === 'enterprise') return 'Contact sales'
  return centsToPrice(interval === 'annual' ? plan?.annual_price_cents : plan?.monthly_price_cents, interval)
}

function normalizeError(error) {
  if (error instanceof BillingApiError) {
    if (error.status === 401) return 'Sign in to manage workspace billing.'
    if (error.status === 409) return error.payload?.message || error.message
    return error.message
  }
  return 'Billing service is unavailable. Please try again.'
}

function statusTone(status) {
  if (status === 'active' || status === 'trialing') return 'success'
  if (status === 'past_due' || status === 'unpaid' || status === 'incomplete' || status === 'expired') return 'warning'
  if (status === 'canceled' || status === 'cancelled' || status === 'incomplete_expired') return 'danger'
  return 'neutral'
}

const ALERT_TONES = {
  info: { icon: Info, box: 'border-info/30 bg-info-soft', icn: 'text-info' },
  warning: { icon: AlertTriangle, box: 'border-warning/30 bg-warning-soft', icn: 'text-warning' },
  error: { icon: XCircle, box: 'border-danger/30 bg-danger-soft', icn: 'text-danger' },
}

function Alert({ tone = 'info', title, children, actions, ...rest }) {
  const t = ALERT_TONES[tone]
  const Icon = t.icon
  return (
    <div className={cx('flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-start', t.box)} {...rest}>
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Icon className={cx('mt-0.5 h-5 w-5 flex-shrink-0', t.icn)} aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-base font-semibold text-fg">{title}</p>
          {children && <p className="mt-0.5 text-sm text-muted">{children}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-shrink-0 flex-wrap gap-2 pl-8 sm:pl-0">{actions}</div>}
    </div>
  )
}

function UsageBar({ used = 0, limit, remaining, label, unit }) {
  const unlimited = limit === null || limit === undefined || limit === -1
  const percent = unlimited || !limit ? 0 : Math.min(100, Math.round((used / limit) * 100))
  const exhausted = !unlimited && remaining === 0
  const nearLimit = !unlimited && percent >= 80 && !exhausted
  const tone = exhausted ? 'danger' : nearLimit ? 'warning' : 'normal'
  const displayUsed = unit === 'bytes' ? formatBytes(used) : Number(used || 0).toLocaleString()
  const displayLimit = formatLimit(limit, unit)
  const displayRemaining = unlimited ? 'Unlimited' : unit === 'bytes' ? formatBytes(remaining || 0) : Number(remaining || 0).toLocaleString()

  const NoteIcon = exhausted ? XCircle : nearLimit ? AlertTriangle : CheckCircle2
  const note = unlimited ? 'Unlimited on this plan' : exhausted ? 'Limit exhausted' : nearLimit ? 'Approaching plan limit' : 'Within plan limit'

  return (
    <div className={cx('flex min-w-0 flex-col gap-2 rounded-lg border bg-surface p-4', tone === 'danger' ? 'border-danger/40' : tone === 'warning' ? 'border-warning/40' : 'border-line')}>
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <p className="truncate text-base font-medium text-fg">{label}</p>
        <p className="flex-shrink-0 text-sm text-muted tabular">
          <span className="font-medium text-fg">{displayUsed}</span> / {displayLimit}
        </p>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-label={`${label} usage`}
        aria-valuemin={0}
        aria-valuemax={unlimited ? undefined : 100}
        aria-valuenow={unlimited ? undefined : percent}
        aria-valuetext={unlimited ? `${displayUsed} used, unlimited plan limit` : `${percent}% used`}
      >
        <span
          className={cx('block h-full rounded-full', tone === 'danger' ? 'bg-danger' : tone === 'warning' ? 'bg-warning' : unlimited ? 'bg-primary/25' : 'bg-primary')}
          style={{ width: `${unlimited ? 100 : percent}%` }}
        />
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
        <span className={cx('flex items-center gap-1', tone === 'danger' ? 'font-medium text-danger' : tone === 'warning' ? 'font-medium text-warning' : 'text-muted')}>
          <NoteIcon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
          {note}
        </span>
        <span className="text-subtle tabular">{displayRemaining} remaining</span>
      </div>
    </div>
  )
}

function UpgradeNotice({ title, description, onUpgrade, onPortal, portalAvailable, loading }) {
  return (
    <Alert
      tone="info"
      role="status"
      title={title}
      actions={(
        <>
          <button type="button" onClick={onUpgrade} disabled={loading} className="btn-primary">
            Upgrade
          </button>
          {portalAvailable && (
            <button type="button" onClick={onPortal} disabled={loading} className="btn-secondary">
              Manage billing
            </button>
          )}
        </>
      )}
    >
      {description}
    </Alert>
  )
}

function Detail({ term, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-subtle">{term}</dt>
      <dd className="mt-0.5 break-words text-base text-fg">{children}</dd>
    </div>
  )
}

export default function BillingPortal() {
  const { apiHeaders, isAuthenticated, isGuest, guestUsage, guestLimits } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const client = useMemo(() => createBillingClient(apiHeaders), [apiHeaders])
  const [state, setState] = useState({ current: null, plans: [], loading: true, refreshing: false })
  const [error, setError] = useState(null)
  const [interval, setInterval] = useState('monthly')
  const [checkoutPlan, setCheckoutPlan] = useState(null)
  const [portalLoading, setPortalLoading] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  const search = new URLSearchParams(location.search)
  const returnedFromCheckout = search.get('checkout')
  const returnedFromPortal = search.get('portal')
  // Rendered both at /app/billing (own page) and inside the settings layout.
  const embedded = location.pathname.startsWith('/app/settings')

  const loadBilling = useCallback(async ({ refreshing = false } = {}) => {
    setError(null)
    setState((prev) => ({ ...prev, loading: !refreshing, refreshing }))
    try {
      const plansResult = await client.getPlans()
      let current = null
      if (isAuthenticated) {
        current = await client.getCurrent()
      }
      setState({ plans: plansResult.plans || [], current, loading: false, refreshing: false })
    } catch (err) {
      setError(normalizeError(err))
      setState((prev) => ({ ...prev, loading: false, refreshing: false }))
    }
  }, [client, isAuthenticated])

  useEffect(() => {
    loadBilling()
  }, [loadBilling])

  useEffect(() => {
    if (!returnedFromCheckout && !returnedFromPortal) return
    if (returnedFromCheckout === 'cancelled') return
    if (retryCount >= 4) return
    const timer = setTimeout(() => {
      setRetryCount((count) => count + 1)
      loadBilling({ refreshing: true })
    }, retryCount === 0 ? 750 : 1500)
    return () => clearTimeout(timer)
  }, [returnedFromCheckout, returnedFromPortal, retryCount, loadBilling])

  const currentPlanId = state.current?.subscription?.plan_id || (isGuest ? 'guest' : 'free')
  const portalAvailable = Boolean(state.current?.billing?.portal_available)
  const paymentStatus = state.current?.billing?.payment_status || state.current?.subscription?.status
  const trialDays = daysUntil(state.current?.trial?.ends_at)
  const visiblePlans = state.plans.filter((plan) => plan.is_public !== false && plan.is_active !== false)
  const usageSource = state.current?.usage || (isGuest ? {
    upload_count: guestUsage?.upload_count || 0,
    query_count: guestUsage?.query_count || 0,
    report_count: guestUsage?.report_count || 0,
    export_count: guestUsage?.export_count || 0,
    storage_bytes: 0,
  } : {})
  const limitSource = state.current?.limits || (isGuest ? {
    upload_count: guestLimits?.upload_count,
    query_count: guestLimits?.query_count,
    report_count: guestLimits?.report_count,
    export_count: guestLimits?.export_count,
    storage_bytes: guestLimits?.max_file_size_bytes,
  } : {})
  const remainingSource = state.current?.remaining_quota || {}

  const createCheckout = async (planId) => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    setCheckoutPlan(planId)
    setError(null)
    try {
      const returnUrl = `${window.location.origin}/app/settings/billing?checkout=success`
      const cancelUrl = `${window.location.origin}/app/settings/billing?checkout=cancelled`
      const data = await client.createCheckout({ plan_id: planId, interval, success_url: returnUrl, cancel_url: cancelUrl })
      const checkoutUrl = data.checkout_url || data.url
      if (!checkoutUrl || !isSafeBillingRedirect(checkoutUrl)) {
        setError('Checkout could not be opened safely. Please contact support.')
        return
      }
      window.location.assign(checkoutUrl)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setCheckoutPlan(null)
    }
  }

  const openPortal = async () => {
    setPortalLoading(true)
    setError(null)
    try {
      const data = await client.createPortal({ return_url: `${window.location.origin}/app/settings/billing?portal=returned` })
      const portalUrl = data.portal_url || data.url
      if (!portalUrl || !isSafeBillingRedirect(portalUrl)) {
        setError('Billing portal could not be opened safely. Please contact support.')
        return
      }
      window.location.assign(portalUrl)
    } catch (err) {
      setError(normalizeError(err))
    } finally {
      setPortalLoading(false)
    }
  }

  const wrapperClass = embedded
    ? 'flex w-full min-w-0 flex-col gap-6'
    : 'mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 lg:py-8'

  if (state.loading) {
    return (
      <div className={wrapperClass} aria-busy="true">
        <p className="sr-only" role="status">Loading billing workspace...</p>
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Skeleton className="h-56 lg:col-span-2" />
          <Skeleton className="h-56" />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      </div>
    )
  }

  const HeadingTag = embedded ? 'h2' : 'h1'
  const SubHeadingTag = embedded ? 'h3' : 'h2'
  const planStatus = state.current?.subscription?.status || (isGuest ? 'guest' : 'free')
  const isFreeTier = currentPlanId === 'free' || currentPlanId === 'guest'
  const needsPaymentAttention = paymentStatus === 'past_due' || paymentStatus === 'unpaid'

  return (
    <div className={wrapperClass} data-testid="billing-dashboard">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <HeadingTag className={cx('font-semibold text-fg', embedded ? 'text-xl' : 'text-2xl')}>Plan and usage</HeadingTag>
          <p className="mt-1 max-w-2xl text-base text-muted">See your current plan, how much of it you've used, and change plans when you need more.</p>
        </div>
        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={state.refreshing}
          onClick={() => loadBilling({ refreshing: true })}
          disabled={state.refreshing}
          className="self-start sm:self-auto"
        >
          {state.refreshing ? 'Refreshing...' : 'Refresh'}
        </Button>
      </header>

      {(returnedFromCheckout === 'success' || returnedFromPortal === 'returned') && (
        <Alert tone="info" role="status" aria-live="polite" title="Processing subscription update">
          We're refreshing your workspace while the payment provider confirms the change. Your plan updates as soon as it's confirmed.
        </Alert>
      )}

      {returnedFromCheckout === 'cancelled' && (
        <Alert tone="warning" role="status" title="Checkout cancelled">
          Your subscription was not changed. You can start checkout again when ready.
        </Alert>
      )}

      {error && (
        <Alert tone="error" role="alert" title="Billing action needs attention">
          {error}
        </Alert>
      )}

      <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3" aria-label="Current plan">
        <div className="card card-pad min-w-0 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-muted">Current plan</p>
              <SubHeadingTag className="mt-0.5 text-2xl font-semibold text-fg">{state.current?.plan?.name || (isGuest ? 'Guest' : 'Free')}</SubHeadingTag>
            </div>
            <Badge tone={statusTone(planStatus)}>{planStatus === 'guest' ? 'Guest access' : friendlyBillingStatus(planStatus)}</Badge>
          </div>
          <dl className="mt-5 grid grid-cols-1 gap-x-6 gap-y-4 border-t border-line pt-5 sm:grid-cols-2 xl:grid-cols-3">
            <Detail term="Renewal date">{formatDate(state.current?.subscription?.renews_at || state.current?.subscription?.current_period_end)}</Detail>
            <Detail term="Billing period">{formatDate(state.current?.subscription?.current_period_start)} – {formatDate(state.current?.subscription?.current_period_end)}</Detail>
            <Detail term="Payment status">{friendlyBillingStatus(paymentStatus)}</Detail>
            <Detail term="Billing portal">{portalAvailable ? 'Available' : 'Not available yet'}</Detail>
            <Detail term="Cancellation">{state.current?.subscription?.cancel_at_period_end ? 'Cancels at period end' : state.current?.subscription?.canceled_at ? 'Cancelled' : 'Not scheduled'}</Detail>
            <Detail term="Trial">{state.current?.trial?.active ? `${trialDays ?? 0} days left` : state.current?.trial?.expired ? 'Expired' : 'Not active'}</Detail>
          </dl>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <button type="button" className="btn-primary" onClick={() => createCheckout('pro')} disabled={checkoutPlan !== null}>
              {checkoutPlan ? 'Starting checkout...' : isFreeTier ? 'Upgrade' : 'Change plan'}
              {!checkoutPlan && <ArrowUpRight className="h-4 w-4" aria-hidden="true" />}
            </button>
            <button type="button" className="btn-secondary" onClick={openPortal} disabled={!portalAvailable || portalLoading}>
              {portalLoading ? 'Opening portal...' : 'Manage billing'}
            </button>
          </div>
        </div>

        <div className={cx('card card-pad flex min-w-0 flex-col gap-3', needsPaymentAttention && 'border-warning/40')}>
          <p className="text-sm text-muted">Trial and payment</p>
          <SubHeadingTag className="flex items-center gap-2 text-lg font-semibold text-fg">
            {needsPaymentAttention
              ? <AlertTriangle className="h-5 w-5 flex-shrink-0 text-warning" aria-hidden="true" />
              : <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-success" aria-hidden="true" />}
            {state.current?.trial?.active ? 'Trial active' : friendlyBillingStatus(paymentStatus)}
          </SubHeadingTag>
          <p className="text-sm text-muted">
            {state.current?.trial?.active
              ? `Your trial ends ${formatDate(state.current.trial.ends_at)}. Upgrade any time before then to keep your paid features.`
              : needsPaymentAttention
                ? 'Payment needs attention. Open the billing portal to update your payment details or retry the charge.'
                : state.current?.subscription?.cancel_at_period_end
                  ? `Access continues until ${formatDate(state.current.subscription.current_period_end)}.`
                  : 'Your billing is in good standing.'}
          </p>
          {(needsPaymentAttention || state.current?.subscription?.cancel_at_period_end) && (
            <button type="button" className="btn-secondary mt-auto self-start" onClick={openPortal} disabled={!portalAvailable || portalLoading}>
              Resolve in portal
            </button>
          )}
        </div>
      </section>

      <section className="flex min-w-0 flex-col gap-4" aria-label="Usage dashboard">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <SubHeadingTag className="text-lg font-semibold text-fg">Workspace limits</SubHeadingTag>
            <p className="mt-0.5 text-sm text-muted">How much of your plan you've used this billing period.</p>
          </div>
          <p className="text-sm text-subtle">Resets {formatDate(state.current?.subscription?.current_period_end)}</p>
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {METRICS.map(([metric, label, unit]) => (
            <UsageBar
              key={metric}
              metric={metric}
              label={label}
              unit={unit}
              used={usageSource?.[metric] || 0}
              limit={limitSource?.[metric]}
              remaining={remainingSource?.[metric]}
            />
          ))}
        </div>
      </section>

      <section className="flex min-w-0 flex-col gap-4" aria-label="Plan comparison">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <SubHeadingTag className="text-lg font-semibold text-fg">Compare available plans</SubHeadingTag>
            <p className="mt-0.5 text-sm text-muted">Prices shown per {interval === 'annual' ? 'year' : 'month'}.</p>
          </div>
          <div className="inline-flex rounded-md border border-line bg-surface-muted p-0.5" role="group" aria-label="Billing interval">
            {[['monthly', 'Monthly'], ['annual', 'Annual']].map(([value, text]) => (
              <button
                key={value}
                type="button"
                aria-pressed={interval === value}
                onClick={() => setInterval(value)}
                className={cx(
                  'h-8 rounded px-3 text-sm font-medium transition-colors duration-fast focus-ring',
                  interval === value ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
                )}
              >
                {text}
              </button>
            ))}
          </div>
        </div>

        <div className="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
          {visiblePlans.map((plan) => {
            const isCurrent = currentPlanId === plan.plan_id
            const isEnterprise = plan.plan_id === 'enterprise'
            const isRecommended = plan.plan_id === 'pro'
            return (
              <article
                key={plan.plan_id}
                className={cx('card card-pad flex min-w-0 flex-col gap-4', isCurrent ? 'border-primary' : isRecommended && 'border-line-strong')}
                aria-current={isCurrent ? 'true' : undefined}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-md font-semibold text-fg">{plan.name}</h4>
                    {isCurrent && <Badge tone="primary">Current</Badge>}
                    {!isCurrent && isRecommended && <Badge tone="info">Recommended</Badge>}
                  </div>
                  {plan.description && <p className="mt-1 text-sm text-muted">{plan.description}</p>}
                  <p className="mt-3 text-2xl font-semibold text-fg tabular">{planPrice(plan, interval)}</p>
                </div>
                <ul className="flex flex-col gap-2 text-sm text-fg">
                  {[
                    `${formatLimit(plan.limits?.ai_prompt_count ?? plan.limits?.query_count)} AI prompts`,
                    `${formatLimit(plan.limits?.upload_count)} uploads`,
                    `${formatLimit(plan.limits?.storage_bytes, 'bytes')} storage`,
                    `${formatLimit(plan.limits?.member_count)} members`,
                  ].map((line) => (
                    <li key={line} className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-success" aria-hidden="true" />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-auto">
                  {isCurrent ? (
                    <button type="button" className="btn-secondary w-full" disabled>Current plan</button>
                  ) : isEnterprise ? (
                    <button type="button" className="btn-secondary w-full" onClick={() => navigate('/contact')}>Contact sales</button>
                  ) : (
                    <button type="button" className="btn-primary w-full" onClick={() => createCheckout(plan.plan_id)} disabled={checkoutPlan !== null}>
                      {checkoutPlan === plan.plan_id ? 'Starting checkout...' : isFreeTier ? `Upgrade to ${plan.name}` : `Change to ${plan.name}`}
                    </button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
        {visiblePlans.length === 0 && !error && (
          <p className="flex items-center gap-2 rounded-lg border border-line bg-surface-muted p-4 text-sm text-muted">
            <AlertCircle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
            Plans couldn't be loaded right now. Select Refresh to try again.
          </p>
        )}
      </section>

      <UpgradeNotice
        title="Reached a limit?"
        description="Your work stays saved when you hit a plan limit. Upgrade for higher limits, or manage your subscription in the billing portal."
        onUpgrade={() => createCheckout('pro')}
        onPortal={openPortal}
        portalAvailable={portalAvailable}
        loading={checkoutPlan !== null || portalLoading}
      />
    </div>
  )
}
