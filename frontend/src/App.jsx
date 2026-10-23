import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import { StatusScreen } from './components/shell/StatusScreen'

import ErrorBoundary from './components/ErrorBoundary'
import SEO from './components/marketing/SEO'


// ── Route-level code splitting ───────────────────────────────────────────────
// Marketing visitors never download the workspace (chat, markdown, spreadsheet,
// settings, billing); workspace users never download the marketing pages.
const named = (loader, name) => lazy(() => loader().then(m => ({ default: m[name] })))
const AppShell = lazy(() => import('./components/shell/AppShell'))
const AuthModal = lazy(() => import('./components/AuthModal'))
const ChatWindow = lazy(() => import('./components/ChatWindow'))
const SpreadsheetPage = lazy(() => import('./components/views/SpreadsheetPage'))
const ReportsPage = lazy(() => import('./components/views/ReportsPage'))
const SavedPage = lazy(() => import('./components/views/SavedPage'))
const DatasetManager = lazy(() => import('./components/DatasetManager'))
const OnboardingFlow = lazy(() => import('./components/OnboardingFlow'))
const BillingPortal = lazy(() => import('./components/BillingPortal'))
const DashboardHome = lazy(() => import('./components/DashboardHome'))
const HomePage = lazy(() => import('./pages/marketing/HomePage'))
const FeaturesPage = lazy(() => import('./pages/marketing/FeaturesPage'))
const UseCasesPage = lazy(() => import('./pages/marketing/UseCasesPage'))
const SecurityPage = lazy(() => import('./pages/marketing/SecurityPage'))
const PricingPage = lazy(() => import('./pages/marketing/PricingPage'))
const AboutPage = lazy(() => import('./pages/marketing/AboutPage'))
const ContactPage = lazy(() => import('./pages/marketing/ContactPage'))
const DocsPage = lazy(() => import('./pages/marketing/DocsPage'))
const NotFoundPage = lazy(() => import('./pages/marketing/NotFoundPage'))
const PrivacyPolicy = named(() => import('./components/LegalPages'), 'PrivacyPolicy')
const TermsOfService = named(() => import('./components/LegalPages'), 'TermsOfService')
const CookiePolicy = named(() => import('./components/LegalPages'), 'CookiePolicy')
const AcceptableUsePolicy = named(() => import('./components/LegalPages'), 'AcceptableUsePolicy')
const SettingsLayout = lazy(() => import('./components/SettingsLayout'))
const ProfileSettings = named(() => import('./components/SettingsLayout'), 'ProfileSettings')
const WorkspaceSettings = named(() => import('./components/SettingsLayout'), 'WorkspaceSettings')
const TeamMembersSettings = named(() => import('./components/SettingsLayout'), 'TeamMembersSettings')
const SecuritySessionsSettings = named(() => import('./components/SettingsLayout'), 'SecuritySessionsSettings')

function ViewFallback() {
  return (
    <div className="space-y-3 p-6" role="status" aria-label="Loading">
      <div className="skeleton h-6 w-48" />
      <div className="skeleton h-40 w-full" />
    </div>
  )
}




// ── Auth Modal Route Guards & Direct Entries ─────────────────────────────────
function AuthRouteWrapper({ tab }) {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/app/analyze')
    }
  }, [isAuthenticated, navigate])

  return (
    <div className="h-[100dvh] overflow-y-auto bg-bg">
      <SEO
        title={tab === 'signup' ? 'Create Account' : tab === 'forgot' ? 'Reset Password' : 'Sign In'}
        description="Secure DataPilot authentication screen."
        canonicalPath={tab === 'signup' ? '/signup' : tab === 'forgot' ? '/forgot-password' : '/login'}
        noindex
      />
      <AuthModal open={true} onClose={() => navigate('/app/analyze')} defaultTab={tab} variant="page" />
    </div>
  )
}

function GuestModeTrigger({ message = 'Starting your free workspace' }) {
  const { initGuestSession } = useAuth()
  const navigate = useNavigate()
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    const startGuestMode = async () => {
      setFailed(false)
      const started = await initGuestSession()
      if (cancelled) return
      if (started) {
        navigate('/app/analyze', { replace: true })
        return
      }
      setFailed(true)
    }
    startGuestMode()
    return () => { cancelled = true }
  }, [initGuestSession, navigate, attempt])

  if (failed) {
    return (
      <StatusScreen
        state="error"
        title="We couldn't start a guest workspace"
        message="The DataPilot service didn't respond. Check your connection and try again, or create a free account to keep your work."
        actions={(
          <>
            <button type="button" className="btn-primary" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
            <Link to="/signup" className="btn-secondary">Create free account</Link>
          </>
        )}
      />
    )
  }
  return <StatusScreen title={message} message="This takes a few seconds." />
}

function OAuthCallback({ provider }) {
  const { completeSocialLogin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState(null)

  useEffect(() => {
    const finishLogin = async () => {
      const params = new URLSearchParams(location.search)
      const providerError = params.get('error')
      if (providerError) {
        setError(`Sign-in was cancelled or failed (${providerError}).`)
        return
      }

      const code = params.get('code')
      const state = params.get('state')
      if (!code || !state) {
        setError('The sign-in link is incomplete. Please start signing in again.')
        return
      }

      try {
        const redirectUri = `${window.location.origin}/auth/oauth/${provider}/callback`
        await completeSocialLogin(provider, code, state, redirectUri)
        navigate('/app/analyze', { replace: true })
      } catch (err) {
        setError(err.message || 'Sign-in failed. Please try again.')
      }
    }
    finishLogin()
  }, [completeSocialLogin, location.search, navigate, provider])

  if (error) {
    return (
      <StatusScreen
        state="error"
        title="Sign-in didn't finish"
        message={error}
        actions={<Link to="/login" className="btn-primary">Back to sign in</Link>}
      />
    )
  }
  return <StatusScreen title="Finishing sign-in" />
}

function RouteGuard({ children }) {
  const { isAuthenticated, isGuest, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && !isAuthenticated && !isGuest) {
      navigate('/login')
    }
  }, [loading, isAuthenticated, isGuest, navigate])

  if (loading) {
    return <StatusScreen title="Opening your workspace" />
  }

  return children
}


// ── Main App Router Entry Point ──────────────────────────────────────────────
export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<ViewFallback />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/demo" element={<GuestModeTrigger message="Loading demo workspace..." />} />
          <Route path="/try-free" element={<GuestModeTrigger />} />
          <Route path="/login" element={<AuthRouteWrapper tab="login" />} />
          <Route path="/signup" element={<AuthRouteWrapper tab="signup" />} />
          <Route path="/forgot-password" element={<AuthRouteWrapper tab="forgot" />} />
          <Route path="/auth/oauth/google/callback" element={<OAuthCallback provider="google" />} />
          <Route path="/auth/oauth/microsoft/callback" element={<OAuthCallback provider="microsoft" />} />
          
          {/* Marketing sub-pages */}
          <Route path="/features" element={<FeaturesPage />} />
          <Route path="/use-cases" element={<UseCasesPage />} />
          <Route path="/security" element={<SecurityPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage />} />
          <Route path="/docs" element={<DocsPage />} />

          {/* Legal pages */}
          <Route path="/legal/privacy" element={<PrivacyPolicy />} />
          <Route path="/legal/terms" element={<TermsOfService />} />
          <Route path="/legal/cookie-policy" element={<CookiePolicy />} />
          <Route path="/legal/acceptable-use" element={<AcceptableUsePolicy />} />
          <Route path="/onboarding" element={<OnboardingFlow />} />
          
          {/* Protected App Routes */}
          <Route path="/app" element={<RouteGuard><AppShell /></RouteGuard>}>
            <Route path="analyze" element={<ChatWindow />} />
            <Route path="datasets" element={<DatasetManager />} />
            <Route path="spreadsheet" element={<SpreadsheetPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="saved" element={<SavedPage />} />

            {/* Old URLs from before the MVP consolidation keep working. */}
            <Route path="dashboard" element={<Navigate to="/app/reports?view=insights" replace />} />
            <Route path="report" element={<Navigate to="/app/reports?view=builder" replace />} />
            <Route path="presentation" element={<Navigate to="/app/reports" replace />} />
            <Route path="templates" element={<Navigate to="/app/analyze" replace />} />
            <Route path="history" element={<Navigate to="/app/analyze" replace />} />
            <Route path="billing" element={<BillingPortal />} />
            
            {/* Settings Sub-routes */}
            <Route path="settings" element={<SettingsLayout />}>
              <Route path="profile" element={<ProfileSettings />} />
              <Route path="workspace" element={<WorkspaceSettings />} />
              <Route path="members" element={<TeamMembersSettings />} />
              <Route path="providers" element={<Navigate to="/app/settings/profile" replace />} />
              <Route path="security" element={<SecuritySessionsSettings />} />
              <Route path="billing" element={<BillingPortal />} />
              <Route index element={<Navigate to="profile" replace />} />
            </Route>

            <Route index element={<DashboardHome />} />
          </Route>

          {/* Public fallback */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
