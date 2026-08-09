import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import SEO from '../../components/marketing/SEO'
import SectionContainer from '../../components/marketing/SectionContainer'
import { useAuth } from '../../contexts/AuthContext'
import {
  centsToPrice,
  createBillingClient,
  formatLimit,
  friendlyBillingStatus,
  isSafeBillingRedirect,
} from '../../lib/billingClient'

function planPrice(plan, interval) {
  if (plan?.plan_id === 'enterprise') return 'Contact sales'
  return centsToPrice(interval === 'annual' ? plan?.annual_price_cents : plan?.monthly_price_cents, interval)
}

export default function PricingPage() {
  const { apiHeaders, isAuthenticated, isGuest } = useAuth()
  const navigate = useNavigate()
  const client = useMemo(() => createBillingClient(apiHeaders), [apiHeaders])
  const [plans, setPlans] = useState([])
  const [current, setCurrent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [interval, setInterval] = useState('monthly')
  const [pendingPlan, setPendingPlan] = useState(null)

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
      const result = await client.createCheckout({
        plan_id: planId,
        interval,
        success_url: `${window.location.origin}/app/settings/billing?checkout=success`,
        cancel_url: `${window.location.origin}/pricing?checkout=cancelled`,
      })
      const checkoutUrl = result.checkout_url || result.url
      if (!checkoutUrl || !isSafeBillingRedirect(checkoutUrl)) {
        setError('Checkout could not be opened safely. Please contact support.')
        return
      }
      window.location.assign(checkoutUrl)
    } catch (err) {
      setError(err?.payload?.message || err?.message || 'Checkout could not be started.')
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
        description="Compare DataPilot plans using backend subscription data, trial status, and secure checkout actions."
        canonicalPath="/pricing"
      />
      <section className="pricing-hero">
        <span>Pricing</span>
        <h1>Plans for spreadsheet analytics teams</h1>
        <p>Compare workspace limits, start checkout securely, or manage an existing subscription through the billing portal.</p>
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
            <span className="billing-eyebrow">Backend plan catalog</span>
            <h2>Choose a plan</h2>
            {current && <p>{friendlyBillingStatus(current.subscription?.status)} on {current.plan?.name || current.subscription?.plan_id}</p>}
          </div>
          <div className="billing-segment" role="group" aria-label="Billing interval">
            <button type="button" className={interval === 'monthly' ? 'is-active' : ''} onClick={() => setInterval('monthly')}>Monthly</button>
            <button type="button" className={interval === 'annual' ? 'is-active' : ''} onClick={() => setInterval('annual')}>Annual</button>
          </div>
        </div>

        {error && (
          <div className="billing-alert billing-alert-error" role="alert">
            <strong>Pricing action needs attention</strong>
            <p>{error}</p>
          </div>
        )}

        {loading ? (
          <div className="billing-loading" role="status">Loading plan catalog...</div>
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
                    <strong>{planPrice(plan, interval)}</strong>
                  </div>
                  <ul>
                    <li>{formatLimit(plan.limits?.ai_prompt_count ?? plan.limits?.query_count)} AI prompts</li>
                    <li>{formatLimit(plan.limits?.upload_count)} uploads</li>
                    <li>{formatLimit(plan.limits?.dataset_count)} datasets</li>
                    <li>{formatLimit(plan.limits?.report_count)} reports</li>
                    <li>{formatLimit(plan.limits?.storage_bytes, 'bytes')} storage</li>
                    <li>{formatLimit(plan.limits?.member_count)} workspace members</li>
                  </ul>
                  {actionForPlan(plan)}
                </article>
              )
            })}
          </div>
        )}

        <div className="pricing-security-note">
          <strong>Security boundary</strong>
          <p>Checkout and portal redirects are generated by DataPilot backend endpoints. The browser never receives Stripe secret keys, webhook secrets, or authoritative entitlement logic.</p>
        </div>
      </SectionContainer>
    </MarketingLayout>
  )
}
