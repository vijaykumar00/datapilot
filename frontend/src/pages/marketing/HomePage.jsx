import { useEffect, useState } from 'react'
import { publicRouteMetadata } from '../../data/marketing'
import CTASection from '../../components/marketing/CTASection'
import MarketingLayout from '../../components/marketing/MarketingLayout'
import SectionContainer from '../../components/marketing/SectionContainer'
import SEO from '../../components/marketing/SEO'
import { Badge, Button, Card } from '../../components/marketing/MarketingPrimitives'

const demoSteps = [
  'Upload workbook',
  'Profile columns',
  'Ask a question',
  'Stream answer',
  'Render chart',
  'Summarize',
  'Explain SQL',
  'Export report',
]

const profitRows = [
  ['Ergo Chair', '$18,420', '31%'],
  ['Standing Desk', '$14,880', '27%'],
  ['Monitor Arm', '$9,730', '24%'],
]

const timeline = [
  ['Upload', 'Bring in CSV or Excel files and let Tallis profile the workbook.'],
  ['Ask', 'Type the question you would normally translate into formulas or pivot tables.'],
  ['Understand', 'Review charts, summaries, and the SQL behind the answer.'],
  ['Share', 'Export a report artifact for a meeting, handoff, or follow-up review.'],
]

const outcomes = [
  ['Ask Questions Naturally', 'No formulas required. Ask for trends, rankings, comparisons, and summaries in plain English.'],
  ['Generate Executive Reports', 'Turn analysis into meeting-ready narratives with charts and clear next steps.'],
  ['Automatic Data Cleaning', 'Spot inconsistent dates, missing values, duplicate rows, and suspicious outliers.'],
  ['Forecast Trends', 'Project future sales or performance from the data already in your workbook.'],
  ['Explain Every Answer', 'Open the SQL and reasoning path so results can be checked before decisions are made.'],
  ['Multi-Sheet Analysis', 'Analyze related sheets without manually merging every tab first.'],
]

const trustItems = [
  ['Private workspaces', 'Your files, chats and reports are only visible to people in your workspace.'],
  ['Numbers you can check', 'Every answer shows the query that produced it, so you can verify it before sharing.'],
  ['Computed, not guessed', 'The AI writes the query; the numbers come from running it on your actual data.'],
  ['Temporary guest data', 'Files uploaded without an account are removed automatically after the trial period.'],
]

const pricing = [
  ['Free', 'Start free', 'Try Tallis in guest mode without creating an account.', '/try-free'],
  ['Pro', 'View plans', 'Higher limits for people who analyse spreadsheets every week.', '/pricing'],
  ['Team', 'View plans', 'Shared workspace, more members and higher limits for teams.', '/pricing'],
  ['Enterprise', 'Contact sales', 'Custom limits, deployment and support for larger organisations.', '/contact'],
]

const faqs = [
  ['What files are supported?', 'CSV, XLSX and XLS files up to 50 MB.'],
  ['Can it handle multiple sheets?', 'Yes. Pick the sheet you want to analyse from any Excel workbook.'],
  ['How accurate are the answers?', 'AI-assisted answers should be verified. Tallis helps by showing charts, summaries, and explainable SQL.'],
  ['Do I need to know SQL or formulas?', 'No. Ask in plain English. The SQL is shown only so you can check the answer if you want to.'],
  ['Is my data private?', 'Your data stays inside your workspace. Only upload data you are allowed to process.'],
  ['Can I export reports?', 'Yes. Results export to CSV and Excel, and reports to PDF, Word, PowerPoint or Excel.'],
]

function ProductPreview({ compact = false }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const timer = window.setInterval(() => {
      setStep((value) => (value + 1) % demoSteps.length)
    }, 1800)
    return () => window.clearInterval(timer)
  }, [])

  const activeStep = demoSteps[step]

  return (
    <div className={`product-preview ${compact ? 'product-preview-compact' : ''}`} aria-label="Animated Tallis product walkthrough">
      <div className="preview-topbar">
        <span className="preview-dot" />
        <span className="preview-dot preview-dot-muted" />
        <span className="preview-dot preview-dot-muted" />
        <span className="preview-title">Sales_Report.xlsx</span>
      </div>

      <div className="preview-grid">
        <aside className="preview-steps" aria-label="Demo progress">
          {demoSteps.map((item, index) => (
            <span key={item} className={index <= step ? 'is-active' : ''}>
              {String(index + 1).padStart(2, '0')} {item}
            </span>
          ))}
        </aside>

        <div className="preview-workspace">
          <div className="upload-pill">
            <span className="upload-icon">XLSX</span>
            <span>
              <strong>Sales_Report.xlsx</strong>
              <small>12 columns, 1,248 rows</small>
            </span>
          </div>

          <div className={`analysis-card ${step >= 1 ? 'is-visible' : ''}`}>
            <span className="pulse-dot" />
            Profiling revenue, cost, product, region, and order date columns.
          </div>

          <div className={`prompt-card ${step >= 2 ? 'is-visible' : ''}`}>
            <span>What were our highest profit products?</span>
          </div>

          <div className={`response-card ${step >= 3 ? 'is-visible' : ''}`}>
            <strong>Top products by profit</strong>
            <p>
              In this sample workbook, Ergo Chair, Standing Desk, and Monitor Arm show the strongest gross profit.
            </p>
          </div>

          <div className={`mini-chart ${step >= 4 ? 'is-visible' : ''}`} aria-label="Sample profit bar chart">
            {profitRows.map(([name, value, width]) => (
              <div key={name} className="chart-row">
                <span>{name}</span>
                <div><i style={{ width }} /></div>
                <strong>{value}</strong>
              </div>
            ))}
          </div>

          <div className={`summary-card ${step >= 5 ? 'is-visible' : ''}`}>
            <strong>Executive summary</strong>
            <p>Margin is concentrated in ergonomic office products. Review regional discounts before the next forecast.</p>
          </div>

          <details className={`sql-drawer ${step >= 6 ? 'is-visible' : ''}`} open={step >= 6}>
            <summary>Explainability SQL</summary>
            <code>SELECT product, SUM(revenue - cost) AS profit FROM sales GROUP BY product ORDER BY profit DESC;</code>
          </details>

          <button className={`export-button ${step >= 7 ? 'is-visible' : ''}`} type="button">
            Export PDF
          </button>
        </div>
      </div>

      <p className="preview-status" aria-live="polite">
        Current step: {activeStep}
      </p>
    </div>
  )
}

function HomeSectionHeader({ eyebrow, title, description }) {
  return (
    <div className="home-section-header">
      <Badge>{eyebrow}</Badge>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  )
}

export default function HomePage() {
  const page = publicRouteMetadata['/']

  return (
    <MarketingLayout>
      <SEO title={page.title} description={page.description} canonicalPath="/" />

      <section className="premium-hero">
        <div className="premium-hero-copy">
          <Badge>AI spreadsheet analytics</Badge>
          <h1>Stop fighting spreadsheets. Start talking to your data.</h1>
          <p>
            Upload an Excel or CSV file and ask questions in plain English. Get the answer as a number,
            table or chart, with the calculation shown so you can trust it.
          </p>
          <div className="marketing-hero-actions">
            <Button to="/try-free">Try it free</Button>
            <Button href="#how-it-works" variant="secondary">How it works</Button>
          </div>
          <div className="hero-proof" aria-label="Product capability summary">
            <span>CSV and Excel</span>
            <span>Explainable SQL</span>
            <span>No formulas needed</span>
          </div>
        </div>
        <ProductPreview compact />
      </section>

      <SectionContainer className="home-band">
        <div id="how-it-works" className="scroll-anchor" />
        <HomeSectionHeader eyebrow="How it works" title="Upload. Ask. Understand. Share." />
        <div className="timeline-grid">
          {timeline.map(([title, description], index) => (
            <div key={title} className="timeline-step">
              <span>{index + 1}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </div>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader
          eyebrow="Feature outcomes"
          title="What you can do with Tallis"
        />
        <div className="outcome-grid">
          {outcomes.map(([title, description]) => (
            <Card key={title} className="outcome-card">
              <h3>{title}</h3>
              <p>{description}</p>
            </Card>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader
          eyebrow="Trust and security"
          title="Built so you can rely on the answer"
        />
        <div className="trust-grid">
          {trustItems.map(([title, description]) => (
            <Card key={title} className="trust-card">
              <h3>{title}</h3>
              <p>{description}</p>
            </Card>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer className="home-band">
        <HomeSectionHeader
          eyebrow="Pricing preview"
          title="Start free, upgrade when you need more"
          description="Pay in ₹ with UPI or card (Razorpay), or in $ by card (Stripe). Cancel any time."
        />
        <div className="pricing-preview-grid">
          {pricing.map(([plan, action, description, to], index) => (
            <Card key={plan} className={index === 0 ? 'pricing-card is-featured' : 'pricing-card'}>
              <h3>{plan}</h3>
              <p>{description}</p>
              <Button to={to} variant={index === 0 ? 'primary' : 'secondary'}>{action}</Button>
            </Card>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader eyebrow="FAQ" title="Practical questions before you try Tallis" />
        <div className="faq-grid">
          {faqs.map(([question, answer]) => (
            <details key={question} className="faq-item">
              <summary>{question}</summary>
              <p>{answer}</p>
            </details>
          ))}
        </div>
      </SectionContainer>

      <CTASection
        title="Ready to stop spending hours inside Excel?"
        description="Start free, upload a workbook, and see how fast a spreadsheet can become a clear answer."
      />
    </MarketingLayout>
  )
}
