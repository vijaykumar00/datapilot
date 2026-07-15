import { Link } from 'react-router-dom'
import { legalRouteMetadata } from '../data/marketing'
import MarketingLayout from './marketing/MarketingLayout'
import SEO from './marketing/SEO'
import { Alert } from './marketing/MarketingPrimitives'

const legalPages = {
  '/legal/privacy': {
    title: 'Privacy Policy',
    sections: [
      ['Data storage and processing', 'DataPilot processes calculations in workspace context and stores files inside the configured backend workspace storage.'],
      ['Guest data expiration', 'Guest sessions and associated uploads are designed for temporary evaluation workflows.'],
      ['Third-party AI integrations', 'When external AI providers are configured, prompts may be sent to the selected provider endpoint. Stored provider keys are encrypted by the application layer.'],
      ['Cookies and local storage', 'DataPilot uses functional session storage and browser preferences. Advertising trackers are not part of the current product foundation.'],
    ],
  },
  '/legal/terms': {
    title: 'Terms of Service',
    sections: [
      ['Usage entitlements', 'Workspace usage is subject to configured limits, account status, and platform integrity protections.'],
      ['User responsibilities', 'Users are responsible for verifying important business, financial, or operational conclusions before acting on generated analysis.'],
      ['Service limitations', 'Generated answers may include AI-assisted reasoning and should be reviewed against source data for high-stakes decisions.'],
    ],
  },
  '/legal/cookie-policy': {
    title: 'Cookie Policy',
    sections: [
      ['Functional storage', 'DataPilot uses functional cookies and browser storage for authentication state, preferences, and workspace continuity.'],
      ['Tracking posture', 'The current product foundation does not include behavioral advertising networks.'],
    ],
  },
  '/legal/acceptable-use': {
    title: 'Acceptable Use Policy',
    sections: [
      ['Platform safety', 'Users must not upload malicious files, attempt unauthorized access, or stress test workspace infrastructure without written approval.'],
      ['Data responsibility', 'Users should only upload datasets they are permitted to process and analyze.'],
      ['Workspace boundaries', 'Attempts to bypass authentication, usage controls, or workspace isolation are prohibited.'],
    ],
  },
}

function LegalPage({ path }) {
  const metadata = legalRouteMetadata[path]
  const page = legalPages[path]

  return (
    <MarketingLayout>
      <SEO title={metadata.title} description={metadata.description} canonicalPath={path} />
      <section className="section-container">
        <article className="section-inner max-w-3xl">
          <div className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border-default)] pb-5">
            <Link to="/" className="btn-ghost">
              Return Home
            </Link>
            <Alert title="Draft pending legal review" tone="warning">
              This page is a product foundation and is not final legal advice.
            </Alert>
          </div>

          <h1 className="text-3xl font-black text-[var(--text-primary)]">{page.title}</h1>
          <p className="mt-3 text-sm font-mono text-[var(--text-muted)]">Last updated: July 2026</p>

          <div className="mt-10 space-y-8">
            {page.sections.map(([title, body], index) => (
              <section key={title}>
                <h2 className="text-lg font-bold text-[var(--text-primary)]">
                  {index + 1}. {title}
                </h2>
                <p className="mt-3 text-base leading-7 text-[var(--text-secondary)]">{body}</p>
              </section>
            ))}
          </div>
        </article>
      </section>
    </MarketingLayout>
  )
}

export function PrivacyPolicy() {
  return <LegalPage path="/legal/privacy" />
}

export function TermsOfService() {
  return <LegalPage path="/legal/terms" />
}

export function CookiePolicy() {
  return <LegalPage path="/legal/cookie-policy" />
}

export function AcceptableUsePolicy() {
  return <LegalPage path="/legal/acceptable-use" />
}
