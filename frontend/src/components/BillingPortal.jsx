import React, { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function BillingPortal() {
  const { apiHeaders, workspaceId } = useAuth()
  const [usage, setUsage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [upgrading, setUpgrading] = useState(false)

  const [billingError, setBillingError] = useState(null)

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001'

  // Trusted redirect domains — only Stripe and own origin are allowed
  const TRUSTED_REDIRECT_DOMAINS = ['stripe.com', 'checkout.stripe.com', window.location.hostname]

  function isTrustedUrl(urlStr) {
    try {
      const parsed = new URL(urlStr)
      return TRUSTED_REDIRECT_DOMAINS.some(d => parsed.hostname === d || parsed.hostname.endsWith('.' + d))
    } catch {
      return false
    }
  }

  useEffect(() => {
    fetchUsage()
  }, [])

  const fetchUsage = async () => {
    try {
      const resp = await fetch(`${API_BASE}/user/usage`, {
        headers: apiHeaders()
      })
      if (resp.ok) {
        const data = await resp.json()
        setUsage(data)
      } else {
        setBillingError('Failed to load billing information. Please refresh.')
      }
    } catch (err) {
      setBillingError('Could not connect to billing service.')
    } finally {
      setLoading(false)
    }
  }

  const handleUpgrade = async (planId) => {
    setUpgrading(true)
    setBillingError(null)
    try {
      const resp = await fetch(`${API_BASE}/billing/checkout`, {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ plan_id: planId })
      })
      const data = await resp.json()
      if (data.checkout_url) {
        if (!isTrustedUrl(data.checkout_url)) {
          setBillingError('Invalid checkout URL returned by server. Please contact support.')
          return
        }
        window.location.href = data.checkout_url
      } else {
        setBillingError(data.detail || data.error || 'Checkout session could not be created.')
      }
    } catch (err) {
      setBillingError('Checkout failed. Please try again or contact support.')
    } finally {
      setUpgrading(false)
    }
  }

  const handlePortalRedirect = async () => {
    setBillingError(null)
    try {
      const resp = await fetch(`${API_BASE}/billing/portal`, {
        method: 'POST',
        headers: apiHeaders()
      })
      const data = await resp.json()
      if (data.portal_url) {
        if (!isTrustedUrl(data.portal_url)) {
          setBillingError('Invalid portal URL returned by server. Please contact support.')
          return
        }
        window.location.href = data.portal_url
      } else {
        setBillingError(data.detail || data.error || 'Could not open billing portal.')
      }
    } catch (err) {
      setBillingError('Portal redirect failed. Please try again.')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <div className="animate-spin rounded-full h-5 w-5 border border-slate-400 border-t-transparent" />
      </div>
    )
  }

  const planName = usage?.plan?.toUpperCase() || 'FREE'
  const isPremium = planName !== 'FREE' && planName !== 'GUEST'

  const getMeterPercent = (current, limit) => {
    if (!limit || limit === -1) return 0
    return Math.min(100, Math.round((current / limit) * 100))
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-6 custom-scrollbar animate-fade-in bg-[#030712]">
      {billingError && (
        <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl px-4 py-3 text-xs text-rose-300 flex items-start gap-2">
          <span>⚠️</span>
          <span>{billingError}</span>
          <button onClick={() => setBillingError(null)} className="ml-auto text-rose-400 hover:text-rose-300">✕</button>
        </div>
      )}
      <div>
        <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
          💳 Billing & Quota Manager
        </h2>
        <p className="text-[11px] text-slate-500 mt-0.5">
          Manage your subscription plans, track monthly analytical quotas, and download payment receipts.
        </p>
      </div>

      {/* Current Subscription Card */}
      <div className="glass p-6 rounded-2xl border border-white/5 relative overflow-hidden flex flex-wrap items-center justify-between gap-6">
        <div>
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Current Workspace Plan</span>
          <div className="flex items-center gap-3.5 mt-2">
            <h3 className="text-2xl font-black text-white">{planName}</h3>
            {isPremium ? (
              <span className="text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-bold">ACTIVE SUBSCRIPTION</span>
            ) : (
              <span className="text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-bold">FREE TIER</span>
            )}
          </div>
        </div>

        {isPremium && (
          <button
            onClick={handlePortalRedirect}
            className="btn-ghost text-[10px] py-2 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10"
          >
            Manage via Stripe Portal →
          </button>
        )}
      </div>

      {/* Usage Quota Meters */}
      {usage && (
        <div className="space-y-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Workspace Quotas</h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Upload Limit */}
            <div className="glass p-4 rounded-xl border border-white/5 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400 font-semibold">Spreadsheet Uploads</span>
                <span className="text-slate-200 font-mono">
                  {usage.current.upload_count} / {usage.limits.upload_count ?? '∞'}
                </span>
              </div>
              <div className="w-full bg-white/5 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-brand-500 h-full rounded-full transition-all duration-300"
                  style={{ width: `${getMeterPercent(usage.current.upload_count, usage.limits.upload_count)}%` }}
                />
              </div>
            </div>

            {/* Query Limit */}
            <div className="glass p-4 rounded-xl border border-white/5 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400 font-semibold">AI Analytics Queries</span>
                <span className="text-slate-200 font-mono">
                  {usage.current.query_count} / {usage.limits.query_count ?? '∞'}
                </span>
              </div>
              <div className="w-full bg-white/5 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-blue-500 h-full rounded-full transition-all duration-300"
                  style={{ width: `${getMeterPercent(usage.current.query_count, usage.limits.query_count)}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Plan Pricing Matrix */}
      {!isPremium && (
        <div className="space-y-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Available Upgrades</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Pro Plan Card */}
            <div className="glass border-brand-500/25 p-5 rounded-2xl flex flex-col justify-between relative group hover:border-brand-500/40 transition-all duration-300">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-brand-300">Pro Plan</h4>
                  <span className="text-[8px] bg-brand-500/10 text-brand-300 border border-brand-500/20 px-2 py-0.5 rounded font-black">POPULAR</span>
                </div>
                <div className="text-xl font-black text-white">$19<span className="text-xs font-medium text-slate-500">/mo</span></div>
                <p className="text-[10px] text-slate-400">Perfect for analysts requiring unlimited conversational queries.</p>
                <ul className="text-[10px] text-slate-500 space-y-2 pt-2">
                  <li>✓ Unlimited uploads & queries</li>
                  <li>✓ Custom provider API key support</li>
                  <li>✓ 10GB workspace storage</li>
                </ul>
              </div>
              <button
                onClick={() => handleUpgrade('pro')}
                disabled={upgrading}
                className="btn-primary w-full py-2 rounded-xl text-xs font-bold border-0 mt-6"
              >
                {upgrading ? 'Initiating checkout...' : 'Upgrade Workspace'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
