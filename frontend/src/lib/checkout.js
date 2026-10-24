/**
 * One upgrade flow for every page:
 *   INR → Razorpay Checkout in a popup (UPI Autopay, cards, eMandate), verified by the server.
 *   USD → Stripe Checkout redirect.
 * Secrets never reach the browser; the server decides the plan after verifying payment.
 */
import { createPaymentsClient, isSafeBillingRedirect } from './billingClient'

const RAZORPAY_SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js'
let scriptPromise = null

function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve()
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const el = document.createElement('script')
      el.src = RAZORPAY_SCRIPT
      el.async = true
      el.onload = () => resolve()
      el.onerror = () => { scriptPromise = null; reject(new Error("Razorpay checkout couldn't load. Check your connection and try again.")) }
      document.head.appendChild(el)
    })
  }
  return scriptPromise
}

function openRazorpay(session) {
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: session.key_id,
      subscription_id: session.subscription_id,
      name: session.name,
      description: session.description,
      prefill: session.prefill,
      theme: { color: '#1F5BD8' },
      handler: (response) => resolve(response),
      modal: { ondismiss: () => reject(Object.assign(new Error('Payment was cancelled.'), { cancelled: true })) },
    })
    rzp.on('payment.failed', (resp) => reject(new Error(resp?.error?.description || 'The payment failed. Try again or use another method.')))
    rzp.open()
  })
}

let providersCache = null
export async function getPaymentProviders() {
  if (!providersCache) providersCache = await createPaymentsClient().getProviders().catch(() => ({}))
  return providersCache
}

/**
 * Returns {status: 'activated'} for Razorpay, or redirects the page for Stripe.
 * Throws with a user-facing message; ``err.cancelled`` is set when the customer closed the popup.
 */
export async function startUpgrade({ billingClient, planId, interval, currency, successUrl, cancelUrl }) {
  const providers = await getPaymentProviders()
  const payments = createPaymentsClient()
  if (currency === 'INR') {
    if (!providers?.razorpay?.configured) {
      throw new Error("Paying in ₹ isn't available yet. Switch to $ to pay by card, or try again later.")
    }
    const session = await payments.createRazorpaySubscription({ plan_id: planId, interval })
    await loadRazorpay()
    const response = await openRazorpay(session)
    await payments.verifyRazorpay({
      razorpay_payment_id: response.razorpay_payment_id,
      razorpay_subscription_id: response.razorpay_subscription_id || session.subscription_id,
      razorpay_signature: response.razorpay_signature,
    })
    return { status: 'activated' }
  }
  if (!providers?.stripe?.configured && providers?.razorpay?.configured) {
    throw new Error("Paying in $ isn't available yet. Switch to ₹ to pay with UPI or card.")
  }
  const result = await billingClient.createCheckout({ plan_id: planId, interval, success_url: successUrl, cancel_url: cancelUrl })
  const url = result.checkout_url || result.url
  if (!url || !isSafeBillingRedirect(url)) throw new Error('Checkout could not be opened safely. Please contact support.')
  window.location.assign(url)
  return { status: 'redirected' }
}
