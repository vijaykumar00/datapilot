import { Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import SEO from '../../components/marketing/SEO'
import { Button, EmptyState } from '../../components/marketing/MarketingPrimitives'

export default function NotFoundPage() {
  const { isAuthenticated, isGuest } = useAuth()
  const canOpenDashboard = isAuthenticated || isGuest

  return (
    <MarketingLayout>
      <SEO
        title="Page Not Found"
        description="The requested DataPilot page could not be found."
        canonicalPath="/404"
        noindex
      />
      <section className="section-container">
        <div className="section-inner">
          <EmptyState
            title="Page not found"
            description="The link may be outdated, or the page may not exist yet. Use the links below to recover without exposing internal error details."
            action={
              <div className="marketing-hero-actions">
                <Button to="/">Back to homepage</Button>
                {canOpenDashboard ? (
                  <Button to="/app/analyze" variant="secondary">
                    Open dashboard
                  </Button>
                ) : (
                  <Button to="/login" variant="secondary">
                    Sign in
                  </Button>
                )}
              </div>
            }
          />
          <p className="mt-6 text-center text-sm text-[var(--text-muted)]">
            You can also visit <Link className="text-[var(--brand-primary)] underline" to="/docs">documentation</Link>.
          </p>
        </div>
      </section>
    </MarketingLayout>
  )
}
