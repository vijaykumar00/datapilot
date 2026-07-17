import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
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

function UsageBar({ metric, used = 0, limit, remaining, label, unit }) {
  const unlimited = limit === null || limit === undefined || limit === -1
  const percent = unlimited || !limit ? 0 : Math.min(100, Math.round((used / limit) * 100))
  const exhausted = !unlimited && remaining === 0
  const nearLimit = !unlimited && percent >= 80 && !exhausted
  const tone = exhausted ? 'danger' : nearLimit ? 'warning' : 'normal'
  const displayUsed = unit === 'bytes' ? formatBytes(used) : Number(used || 0).toLocaleString()
  const displayLimit = formatLimit(limit, unit)
  const displayRemaining = unlimited ? 'Unlimited' : unit === 'bytes' ? formatBytes(remaining || 0) : Number(remaining || 0).toLocaleString()

  return (
    <div className={`billing-usage-row billing-usage-row-${tone}`}>
      <div className="billing-usage-copy">
        <div>
          <strong>{label}</strong>
          <span>{displayUsed} used</span>
        </div>
        <div className="billing-usage-values">
          <span>{displayLimit}</span>
          <span>{displayRemaining} remaining</span>
        </div>
      </div>
      <div
        className="billing-progress"
        role="progressbar"
        aria-label={`${label} usage`}
        aria-valuemin={0}
        aria-valuemax={unlimited ? undefined : 100}
        aria-valuenow={unlimited ? undefined : percent}
        aria-valuetext={unlimited ? `${displayUsed} used, unlimited plan limit` : `${percent}% used`}
      >
        <span style={{ width: `${unlimited ? 100 : percent}%` }} />
      </div>
      <p className="billing-usage-note">
        {unlimited ? 'Unlimited on this plan' : exhausted ? 'Limit exhausted' : nearLimit ? 'Approaching plan limit' : 'Within plan limit'}
      </p>
    </div>
  )
}

function UpgradeNotice({ title, description, onUpgrade, onPortal, portalAvailable, loading }) {
  return (
    <div className="billing-alert billing-alert-warning" role="status">
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <div className="billing-alert-actions">
        <button type="button" onClick={onUpgrade} disabled={loading} className="btn-primary">
          Upgrade
        </button>
        {portalAvailable && (
          <button type="button" onClick={onPortal} disabled={loading} className="btn-secondary">
            Manage billing
          </button>
        )}
      </div>
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

  if (state.loading) {
    return (
      <div className="billing-shell" aria-busy="true">
        <div className="billing-loading" role="status">Loading billing workspace...</div>
      </div>
    )
  }

  return (
    <div className="billing-shell custom-scrollbar" data-testid="billing-dashboard">
      <div className="billing-header">
        <div>
          <span className="billing-eyebrow">Workspace billing</span>
          <h2>Plan and usage</h2>
          <p>Subscription state, usage, and plan actions are synced from the backend billing domain.</p>
        </div>
        <button type="button" onClick={() => loadBilling({ refreshing: true })} disabled={state.refreshing} className="btn-ghost">
          {state.refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {(returnedFromCheckout === 'success' || returnedFromPortal === 'returned') && (
        <div className="billing-alert billing-alert-info" role="status" aria-live="polite">
          <strong>Processing subscription update</strong>
          <p>We are refreshing your workspace while Stripe webhooks finish syncing. Your plan changes only after the backend confirms them.</p>
        </div>
      )}

      {returnedFromCheckout === 'cancelled' && (
        <div className="billing-alert billing-alert-warning" role="status">
          <strong>Checkout cancelled</strong>
          <p>Your subscription was not changed. You can start checkout again when ready.</p>
        </div>
      )}

      {error && (
        <div className="billing-alert billing-alert-error" role="alert">
          <strong>Billing action needs attention</strong>
          <p>{error}</p>
        </div>
      )}

      <section className="billing-current-grid" aria-label="Current plan">
        <div className="billing-current-card">
          <span className="billing-eyebrow">Current plan</span>
          <div className="billing-plan-title">
            <h3>{state.current?.plan?.name || (isGuest ? 'Guest' : 'Free')}</h3>
            <span>{friendlyBillingStatus(state.current?.subscription?.status || (isGuest ? 'guest' : 'free'))}</span>
          </div>
          <dl className="billing-definition-grid">
            <div><dt>Renewal date</dt><dd>{formatDate(state.current?.subscription?.renews_at || state.current?.subscription?.current_period_end)}</dd></div>
            <div><dt>Billing period</dt><dd>{formatDate(state.current?.subscription?.current_period_start)} - {formatDate(state.current?.subscription?.current_period_end)}</dd></div>
            <div><dt>Payment status</dt><dd>{friendlyBillingStatus(paymentStatus)}</dd></div>
            <div><dt>Portal</dt><dd>{portalAvailable ? 'Available' : 'Unavailable'}</dd></div>
            <div><dt>Cancellation</dt><dd>{state.current?.subscription?.cancel_at_period_end ? 'Cancels at period end' : state.current?.subscription?.canceled_at ? 'Cancelled' : 'Not scheduled'}</dd></div>
            <div><dt>Trial</dt><dd>{state.current?.trial?.active ? `${trialDays ?? 0} days left` : state.current?.trial?.expired ? 'Expired' : 'Not active'}</dd></div>
          </dl>
          <div className="billing-action-row">
            <button type="button" className="btn-primary" onClick={() => createCheckout('pro')} disabled={checkoutPlan !== null}>
              {checkoutPlan ? 'Starting checkout...' : currentPlanId === 'free' || currentPlanId === 'guest' ? 'Upgrade' : 'Change plan'}
            </button>
            <button type="button" className="btn-secondary" onClick={openPortal} disabled={!portalAvailable || portalLoading}>
              {portalLoading ? 'Opening portal...' : 'Manage billing'}
            </button>
          </div>
        </div>

        <div className="billing-current-card">
          <span className="billing-eyebrow">Trial and payment</span>
          <h3>{state.current?.trial?.active ? 'Trial active' : friendlyBillingStatus(paymentStatus)}</h3>
          <p className="billing-card-copy">
            {state.current?.trial?.active
              ? `Your trial ends ${formatDate(state.current.trial.ends_at)}. Upgrade when you are ready; backend state remains authoritative.`
              : paymentStatus === 'past_due' || paymentStatus === 'unpaid'
                ? 'Payment needs attention. Open the portal to update payment details or retry billing.'
                : state.current?.subscription?.cancel_at_period_end
                  ? `Access continues until ${formatDate(state.current.subscription.current_period_end)}.`
                  : 'Your workspace billing status is ready for normal usage.'}
          </p>
          {(paymentStatus === 'past_due' || paymentStatus === 'unpaid' || state.current?.subscription?.cancel_at_period_end) && (
            <button type="button" className="btn-secondary" onClick={openPortal} disabled={!portalAvailable || portalLoading}>
              Resolve in portal
            </button>
          )}
        </div>
      </section>

      <section className="billing-section" aria-label="Usage dashboard">
        <div className="billing-section-header">
          <div>
            <span className="billing-eyebrow">Usage dashboard</span>
            <h3>Workspace limits</h3>
          </div>
          <span className="billing-period">Resets {formatDate(state.current?.subscription?.current_period_end)}</span>
        </div>
        <div className="billing-usage-grid">
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

      <section className="billing-section" aria-label="Plan comparison">
        <div className="billing-section-header">
          <div>
            <span className="billing-eyebrow">Plans</span>
            <h3>Compare available plans</h3>
          </div>
          <div className="billing-segment" role="group" aria-label="Billing interval">
            <button type="button" className={interval === 'monthly' ? 'is-active' : ''} onClick={() => setInterval('monthly')}>Monthly</button>
            <button type="button" className={interval === 'annual' ? 'is-active' : ''} onClick={() => setInterval('annual')}>Annual</button>
          </div>
        </div>

        <div className="billing-plan-grid">
          {visiblePlans.map((plan) => {
            const isCurrent = currentPlanId === plan.plan_id
            const isEnterprise = plan.plan_id === 'enterprise'
            return (
              <article key={plan.plan_id} className={`billing-plan-card ${plan.plan_id === 'pro' ? 'is-recommended' : ''} ${isCurrent ? 'is-current' : ''}`}>
                <div>
                  <span className="billing-eyebrow">{plan.plan_id === 'pro' ? 'Recommended' : isCurrent ? 'Current' : 'Plan'}</span>
                  <h4>{plan.name}</h4>
                  <p>{plan.description}</p>
                  <strong className="billing-price">{planPrice(plan, interval)}</strong>
                </div>
                <ul>
                  <li>{formatLimit(plan.limits?.ai_prompt_count ?? plan.limits?.query_count)} AI prompts</li>
                  <li>{formatLimit(plan.limits?.upload_count)} uploads</li>
                  <li>{formatLimit(plan.limits?.storage_bytes, 'bytes')} storage</li>
                  <li>{formatLimit(plan.limits?.member_count)} members</li>
                </ul>
                {isCurrent ? (
                  <button type="button" className="btn-secondary" disabled>Current plan</button>
                ) : isEnterprise ? (
                  <button type="button" className="btn-secondary" onClick={() => navigate('/contact')}>Contact sales</button>
                ) : (
                  <button type="button" className="btn-primary" onClick={() => createCheckout(plan.plan_id)} disabled={checkoutPlan !== null}>
                    {checkoutPlan === plan.plan_id ? 'Starting checkout...' : currentPlanId === 'free' || currentPlanId === 'guest' ? 'Upgrade' : 'Change plan'}
                  </button>
                )}
              </article>
            )
          })}
        </div>
      </section>

      <UpgradeNotice
        title="Reached a limit?"
        description="When the backend blocks a quota or feature, this workspace keeps your work visible and routes the next action through checkout or the Customer Portal."
        onUpgrade={() => createCheckout('pro')}
        onPortal={openPortal}
        portalAvailable={portalAvailable}
        loading={checkoutPlan !== null || portalLoading}
      />
    </div>
  )
}
