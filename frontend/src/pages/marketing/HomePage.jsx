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

const problems = [
  ['Hours creating reports', 'Upload one workbook and generate report-ready summaries in a guided flow.'],
  ['Messy Excel files', 'Surface missing values, inconsistent dates, and outliers before they distort results.'],
  ['Manual formulas', 'Ask questions in plain English instead of rebuilding nested spreadsheet formulas.'],
  ['Pivot table fatigue', 'Turn common business questions into clear answers and charts without manual reshaping.'],
  ['Copy-paste reporting', 'Export a structured executive summary after the analysis is complete.'],
  ['Broken lookups', 'Use multi-sheet context and explainable SQL instead of fragile VLOOKUP chains.'],
]

const timeline = [
  ['Upload', 'Bring in CSV or Excel files and let DataPilot profile the workbook.'],
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

const industries = [
  ['Sales', 'Weekly pipeline spreadsheets', 'Which products drove the highest profit?', 'Ranked products with chart and summary.'],
  ['Finance', 'Budget variance workbooks', 'Where did actuals exceed forecast?', 'Variance table with drivers called out.'],
  ['Accounting', 'Messy transaction exports', 'Which entries need review?', 'Potential duplicates and missing fields.'],
  ['Operations', 'Fulfillment and SLA logs', 'Where are delays increasing?', 'Delay trend and affected process steps.'],
  ['Healthcare', 'Scheduling and capacity sheets', 'Which clinics are overbooked?', 'Capacity view with outlier days.'],
  ['Retail', 'Store sales extracts', 'Which categories are slowing down?', 'Category trend and inventory context.'],
  ['Construction', 'Project cost trackers', 'Which jobs are over budget?', 'Overrun list with percentage variance.'],
  ['Manufacturing', 'Production quality logs', 'Which defects are trending?', 'Defect trend chart and source rows.'],
  ['Education', 'Enrollment spreadsheets', 'Which programs changed fastest?', 'Enrollment movement summary.'],
  ['HR', 'Headcount and hiring trackers', 'Where is time-to-hire longest?', 'Role-level bottleneck analysis.'],
  ['Marketing', 'Campaign exports', 'Which channels convert best?', 'Channel comparison with ROI context.'],
]

const comparisonRows = [
  ['Input method', 'Complex formulas', 'Natural language'],
  ['Cleaning', 'Manual cleanup', 'Automatic issue detection'],
  ['Time spent', 'Hours of workbook work', 'Minutes to a shareable answer'],
  ['Verification', 'Hard to trace', 'Explainable SQL and reasoning'],
  ['Output', 'Screenshots and copy paste', 'Charts, summaries, and exports'],
]

const trustItems = [
  ['Workspace isolation', 'Analysis runs inside the user or guest workspace context already implemented in the app.'],
  ['Encrypted API keys', 'Provider keys are stored using the application encryption path already present in settings.'],
  ['Explainable SQL', 'Answers can expose the query logic so users can verify the calculation path.'],
  ['Guest data expiration', 'Guest mode is designed for temporary evaluation workflows.'],
  ['User-controlled providers', 'Users can configure supported provider keys, including local Ollama workflows.'],
]

const pricing = [
  ['Free', 'Start Free', 'Try DataPilot in guest mode without creating an account.', '/try-free'],
  ['Pro', 'View Plans', 'Upgrade through server-generated Stripe Checkout when ready.', '/pricing'],
  ['Team', 'View Plans', 'Collaborative workspace limits and billing management live in the plan catalog.', '/pricing'],
  ['Enterprise', 'Contact Sales', 'Custom deployment conversations can begin through contact.', '/contact'],
]

const faqs = [
  ['What files are supported?', 'DataPilot is built around CSV and Excel workbook analysis.'],
  ['Can it handle multiple sheets?', 'Yes. Multi-sheet workflows are part of the product direction and current workspace experience.'],
  ['How accurate are the answers?', 'AI-assisted answers should be verified. DataPilot helps by showing charts, summaries, and explainable SQL.'],
  ['Can I use Ollama?', 'Yes. The application includes a local Ollama provider option.'],
  ['Can I use my own API key?', 'Yes. Users can configure supported provider keys in the workspace settings.'],
  ['Is my data private?', 'Data is handled inside workspace boundaries. Avoid uploading data you are not permitted to process.'],
  ['Can I export reports?', 'The product includes report/export workflows, represented in this homepage demo.'],
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
    <div className={`product-preview ${compact ? 'product-preview-compact' : ''}`} aria-label="Animated DataPilot product walkthrough">
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
          <h1>Stop Fighting Spreadsheets. Start Talking To Your Data.</h1>
          <p>
            Upload Excel or CSV files. Ask questions in plain English. Generate charts, forecast trends,
            clean messy data, and create executive reports within seconds.
          </p>
          <div className="marketing-hero-actions">
            <Button to="/try-free">Try Free</Button>
            <Button href="#product-demo" variant="secondary">Watch Demo</Button>
          </div>
          <div className="hero-proof" aria-label="Product capability summary">
            <span>CSV and Excel</span>
            <span>Explainable SQL</span>
            <span>User-controlled providers</span>
          </div>
        </div>
        <ProductPreview compact />
      </section>

      <SectionContainer className="home-band" as="section">
        <div id="product-demo" className="scroll-anchor" />
        <HomeSectionHeader
          eyebrow="Interactive product experience"
          title="From upload to executive summary in one visible flow"
          description="A realistic sample walkthrough of the DataPilot workspace, using sample sales data and product capabilities already represented in the app."
        />
        <ProductPreview />
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader
          eyebrow="Business problems"
          title="The spreadsheet work that slows teams down"
          description="DataPilot is designed for the repetitive reporting work that usually lives in fragile workbook rituals."
        />
        <div className="problem-grid">
          {problems.map(([problem, solution]) => (
            <Card key={problem} className="problem-card">
              <span className="card-icon">!</span>
              <h3>{problem}</h3>
              <p>{solution}</p>
            </Card>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer className="home-band">
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
          title="Built around the result, not the menu item"
          description="Each capability is framed around what analysts and operators need to finish."
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

      <SectionContainer className="home-band">
        <HomeSectionHeader eyebrow="Before and after" title="Replace workbook busywork with a focused answer loop" />
        <div className="before-after">
          <Card className="workflow-card old-workflow">
            <h3>Old workflow</h3>
            {['Excel', 'Cleaning', 'Pivot Tables', 'Charts', 'Formatting', 'Presentation', 'Hours'].map((item) => (
              <span key={item}>{item}</span>
            ))}
          </Card>
          <Card className="workflow-card new-workflow">
            <h3>DataPilot workflow</h3>
            {['Upload', 'Ask', 'Review SQL', 'Download', 'Minutes'].map((item) => (
              <span key={item}>{item}</span>
            ))}
          </Card>
        </div>
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader
          eyebrow="Industry use cases"
          title="Premium spreadsheet workflows across teams"
          description="Each card shows a common workbook problem, an example question, and the expected analysis output."
        />
        <div className="industry-grid">
          {industries.map(([industry, problem, question, result]) => (
            <Card key={industry} className="industry-card">
              <h3>{industry}</h3>
              <p><strong>Problem:</strong> {problem}</p>
              <p><strong>Ask:</strong> "{question}"</p>
              <p><strong>Result:</strong> {result}</p>
            </Card>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer className="home-band">
        <HomeSectionHeader eyebrow="Why DataPilot" title="A clearer path than manual spreadsheet analysis" />
        <div className="comparison-table" role="table" aria-label="Manual Excel compared with DataPilot">
          <div role="row" className="comparison-head">
            <span role="columnheader">Workflow</span>
            <span role="columnheader">Manual Excel</span>
            <span role="columnheader">DataPilot</span>
          </div>
          {comparisonRows.map(([label, manual, datapilot]) => (
            <div role="row" key={label}>
              <span role="cell">{label}</span>
              <span role="cell">{manual}</span>
              <span role="cell">{datapilot}</span>
            </div>
          ))}
        </div>
      </SectionContainer>

      <SectionContainer>
        <HomeSectionHeader
          eyebrow="Trust and security"
          title="Trust signals grounded in implemented product behavior"
          description="No unsupported compliance claims, no fake certifications, and no customer-name theatre."
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
          title="Start free, upgrade through secure billing"
          description="Paid plans now use backend subscription data and server-generated Stripe Checkout or Customer Portal redirects."
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
        <HomeSectionHeader eyebrow="FAQ" title="Practical questions before you try DataPilot" />
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
        title="Ready To Stop Spending Hours Inside Excel?"
        description="Start free, upload a workbook, and see how fast a spreadsheet can become a clear answer."
      />
    </MarketingLayout>
  )
}
