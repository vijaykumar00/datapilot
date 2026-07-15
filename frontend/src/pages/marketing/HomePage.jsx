import { publicRouteMetadata } from '../../data/marketing'
import CTASection from '../../components/marketing/CTASection'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import PageHero from '../../components/marketing/PageHero'
import SectionContainer from '../../components/marketing/SectionContainer'
import SEO from '../../components/marketing/SEO'
import { Badge, Button, Card } from '../../components/marketing/MarketingPrimitives'

const workflowCards = [
  {
    title: 'Upload spreadsheets',
    description: 'Bring CSV or Excel files into a focused analytics workspace.',
  },
  {
    title: 'Ask questions',
    description: 'Use plain language prompts while DataPilot keeps query logic explainable.',
  },
  {
    title: 'Share outputs',
    description: 'Turn answers into charts, saved analysis records, and narrative reports.',
  },
]

export default function HomePage() {
  const page = publicRouteMetadata['/']

  return (
    <MarketingLayout>
      <SEO title={page.title} description={page.description} canonicalPath="/" />
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
        <div className="marketing-kicker">
          <Badge>How it works</Badge>
          <h2>From workbook to answer in one guided flow</h2>
        </div>
        <div className="marketing-foundation-grid">
          {workflowCards.map((card) => (
            <Card key={card.title}>
              <h2>{card.title}</h2>
              <p>{card.description}</p>
            </Card>
          ))}
        </div>
        <div className="marketing-inline-actions">
          <Button to="/demo" variant="secondary">Open demo workspace</Button>
          <Button to="/docs" variant="ghost">Read documentation</Button>
        </div>
      </SectionContainer>

      <CTASection />
    </MarketingLayout>
  )
}
