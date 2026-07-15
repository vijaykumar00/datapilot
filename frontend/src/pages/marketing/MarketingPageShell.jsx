import { publicRouteMetadata } from '../../data/marketing'
import CTASection from '../../components/marketing/CTASection'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import PageHero from '../../components/marketing/PageHero'
import SectionContainer from '../../components/marketing/SectionContainer'
import SEO from '../../components/marketing/SEO'
import { Card } from '../../components/marketing/MarketingPrimitives'

export default function MarketingPageShell({ path }) {
  const page = publicRouteMetadata[path]

  return (
    <MarketingLayout>
      <SEO title={page.title} description={page.description} canonicalPath={path} />
      <PageHero
        eyebrow={page.eyebrow}
        title={page.heading}
        description={page.summary}
        ctaLabel={page.ctaLabel}
        ctaTo={page.ctaTo}
        secondaryCtaLabel={page.secondaryCtaLabel}
        secondaryCtaTo={page.secondaryCtaTo}
      />

      <SectionContainer>
        <div className="marketing-foundation-grid">
          <Card>
            <h2>Route foundation</h2>
            <p>
              This public path is live, refresh-safe in the Vite SPA, and uses shared navigation,
              footer, skip link, and SEO metadata.
            </p>
          </Card>
          <Card>
            <h2>Content readiness</h2>
            <p>
              The page has factual starter copy and calls to action while detailed Sprint 3 content
              remains intentionally out of scope.
            </p>
          </Card>
          <Card>
            <h2>Brand consistency</h2>
            <p>
              Layout, buttons, card styling, focus states, and responsive spacing use DataPilot
              design tokens rather than page-specific styling.
            </p>
          </Card>
        </div>
      </SectionContainer>

      <CTASection />
    </MarketingLayout>
  )
}
