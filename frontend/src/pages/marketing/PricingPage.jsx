import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import SEO from '../../components/marketing/SEO'
import SectionContainer from '../../components/marketing/SectionContainer'
import { useAuth } from '../../contexts/AuthContext'
import {
  createBillingClient,
  defaultCurrency,
  formatPlanPrice,
  friendlyBillingStatus,
  isSafeBillingRedirect,
  planHighlights,
  rememberCurrency,
} from '../../lib/billingClient'
import { startUpgrade } from '../../lib/checkout'

export default function PricingPage() {
  const { apiHeaders, isAuthenticated, isGuest } = useAuth()
  const navigate = useNavigate()
  const client = useMemo(() => createBillingClient(apiHeaders), [apiHeaders])
  const [plans, setPlans] = useState([])
  const [current, setCurrent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [interval, setInterval] = useState('monthly')
  const [currency, setCurrencyState] = useState(defaultCurrency)
  const [pendingPlan, setPendingPlan] = useState(null)
  const setCurrency = (value) => { setCurrencyState(value); rememberCurrency(value) }

  const loadPlans = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const plansResult = await client.getPlans()
      setPlans((plansResult.plans || []).filter((plan) => plan.is_public !== false && plan.is_active !== false))
      if (isAuthenticated) {
        setCurrent(await client.getCurrent())
      } else {
        setCurrent(null)
      }
    } catch {
      setError('Pricing is temporarily unavailable. Please refresh or contact support.')
    } finally {
      setLoading(false)
    }
  }, [client, isAuthenticated])

  useEffect(() => {
    loadPlans()
  }, [loadPlans])

  const currentPlanId = current?.subscription?.plan_id || (isGuest ? 'guest' : null)

  const startCheckout = async (planId) => {
    if (!isAuthenticated) {
      navigate(planId === 'free' ? '/try-free' : '/signup')
      return
    }
    setPendingPlan(planId)
    setError(null)
    try {
      const result = await startUpgrade({
        billingClient: client,
        planId,
        interval,
        currency,
        successUrl: `${window.location.origin}/app/settings/billing?checkout=success`,
        cancelUrl: `${window.location.origin}/pricing?checkout=cancelled`,
      })
      if (result.status === 'activated') navigate('/app/settings/billing?checkout=success')
    } catch (err) {
      if (!err?.cancelled) setError(err?.payload?.message || err?.message || 'Checkout could not be started.')
    } finally {
      setPendingPlan(null)
    }
  }

  const openPortal = async () => {
    setPendingPlan('portal')
    setError(null)
    try {
      const result = await client.createPortal({ return_url: `${window.location.origin}/app/settings/billing?portal=returned` })
      const portalUrl = result.portal_url || result.url
      if (!portalUrl || !isSafeBillingRedirect(portalUrl)) {
        setError('Billing portal could not be opened safely. Please contact support.')
        return
      }
      window.location.assign(portalUrl)
    } catch (err) {
      setError(err?.message || 'Billing portal could not be opened.')
    } finally {
      setPendingPlan(null)
    }
  }

  const actionForPlan = (plan) => {
    if (plan.plan_id === 'enterprise') {
      return <Link to="/contact" className="btn-secondary">Contact sales</Link>
    }
    if (!isAuthenticated) {
      if (plan.plan_id === 'free') {
        return <button type="button" className="btn-primary" onClick={() => navigate('/try-free')}>Try free</button>
      }
      return <button type="button" className="btn-primary" onClick={() => navigate('/signup')}>Sign up to choose</button>
    }
    if (currentPlanId === plan.plan_id) {
      return <button type="button" className="btn-secondary" disabled>Current plan</button>
    }
    if (current?.billing?.portal_available && currentPlanId && currentPlanId !== 'free') {
      return <button type="button" className="btn-secondary" onClick={openPortal} disabled={pendingPlan !== null}>Change in portal</button>
    }
    return (
      <button type="button" className="btn-primary" onClick={() => startCheckout(plan.plan_id)} disabled={pendingPlan !== null}>
        {pendingPlan === plan.plan_id ? 'Starting checkout...' : current?.trial?.active ? 'Upgrade now' : 'Upgrade'}
      </button>
    )
  }

  return (
    <MarketingLayout>
      <SEO
        title="Pricing"
        description="Tallis plans: free to start, Pro and Business in ₹ with UPI, or in $ by card. Instant answers are always unlimited."
        canonicalPath="/pricing"
      />
      <section className="pricing-hero">
        <span>Pricing</span>
        <h1>Simple plans. Your data stays yours.</h1>
        <p>Instant answers are unlimited on every plan. Pay for AI questions, storage and team features only when you need them. Pay in ₹ with UPI or card, or in $ by card.</p>
        <div className="pricing-hero-actions">
          <Link to={isAuthenticated ? '/app/settings/billing' : '/try-free'} className="btn-primary">
            {isAuthenticated ? 'Open billing' : 'Start free'}
          </Link>
          <Link to="/contact" className="btn-secondary">Talk to sales</Link>
        </div>
      </section>

      <SectionContainer>
        <div className="pricing-toolbar">
          <div>
            <span className="billing-eyebrow">Plans</span>
            <h2>Choose a plan</h2>
            {current && <p>{friendlyBillingStatus(current.subscription?.status)} on {current.plan?.name || current.subscription?.plan_id}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="billing-segment" role="group" aria-label="Currency">
              <button type="button" aria-pressed={currency === 'INR'} className={currency === 'INR' ? 'is-active' : ''} onClick={() => setCurrency('INR')}>₹ INR</button>
              <button type="button" aria-pressed={currency === 'USD'} className={currency === 'USD' ? 'is-active' : ''} onClick={() => setCurrency('USD')}>$ USD</button>
            </div>
            <div className="billing-segment" role="group" aria-label="Billing interval">
              <button type="button" aria-pressed={interval === 'monthly'} className={interval === 'monthly' ? 'is-active' : ''} onClick={() => setInterval('monthly')}>Monthly</button>
              <button type="button" aria-pressed={interval === 'annual'} className={interval === 'annual' ? 'is-active' : ''} onClick={() => setInterval('annual')}>Annual · 2 months free</button>
            </div>
          </div>
        </div>

        {error && (
          <div className="billing-alert billing-alert-error" role="alert">
            <strong>Something went wrong</strong>
            <p>{error}</p>
          </div>
        )}

        {loading ? (
          <div className="billing-loading" role="status">Loading plans…</div>
        ) : (
          <div className="pricing-plan-grid">
            {plans.map((plan) => {
              const isCurrent = currentPlanId === plan.plan_id
              const recommended = plan.plan_id === 'pro'
              return (
                <article key={plan.plan_id} className={`pricing-plan-card ${recommended ? 'is-recommended' : ''} ${isCurrent ? 'is-current' : ''}`}>
                  <div>
                    <span className="billing-eyebrow">{recommended ? 'Recommended' : isCurrent ? 'Current plan' : 'Plan'}</span>
                    <h3>{plan.name}</h3>
                    <p>{plan.description}</p>
                    <strong>{formatPlanPrice(plan, currency, interval)}</strong>
                  </div>
                  <ul>
                    {planHighlights(plan).map((line) => <li key={line}>{line}</li>)}
                  </ul>
                  {actionForPlan(plan)}
                </article>
              )
            })}
          </div>
        )}

        <div className="pricing-security-note">
          <strong>Same privacy on every plan</strong>
          <p>Free or paid, your files are never sold or used to train AI, you can switch AI off for a workspace, and you can download or delete everything at any time. Paid plans renew automatically and can be cancelled any time; you keep access until the end of the period you paid for. Every file can have up to 250,000 rows.</p>
        </div>
      </SectionContainer>
    </MarketingLayout>
  )
}
