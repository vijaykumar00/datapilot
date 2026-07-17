import { useEffect, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDataPilot } from '../hooks/useDataPilot'
import { useAuth } from '../contexts/AuthContext'

const suggestedQuestions = [
  'Show monthly sales trends',
  'Find missing values',
  'Forecast revenue',
  'Top products by profit',
  'Worst performing region',
  'Create executive summary',
]

const templates = [
  {
    title: 'Sales',
    problem: 'Weekly sales exports are hard to summarize quickly.',
    questions: ['Top products by profit', 'Monthly revenue by region'],
    output: 'Revenue trend, product ranking, and executive summary.',
  },
  {
    title: 'Finance',
    problem: 'Budget variance workbooks need careful review.',
    questions: ['Where did actuals exceed budget?', 'Which cost centers changed fastest?'],
    output: 'Variance table with flagged drivers.',
  },
  {
    title: 'Inventory',
    problem: 'Stock sheets hide slow movers and shortage risk.',
    questions: ['Which SKUs are below reorder level?', 'What inventory is aging?'],
    output: 'Priority reorder list and aging summary.',
  },
  {
    title: 'HR',
    problem: 'Hiring trackers need bottleneck visibility.',
    questions: ['Where is time-to-hire longest?', 'Which roles are stuck?'],
    output: 'Pipeline health and role-level bottlenecks.',
  },
  {
    title: 'Marketing',
    problem: 'Campaign exports scatter spend and conversion data.',
    questions: ['Which channels convert best?', 'Where is cost per lead rising?'],
    output: 'Channel comparison with ROI context.',
  },
  {
    title: 'Construction',
    problem: 'Project trackers drift from budget and schedule.',
    questions: ['Which jobs are over budget?', 'What milestones are slipping?'],
    output: 'Risk list with cost and timeline notes.',
  },
  {
    title: 'Healthcare',
    problem: 'Capacity sheets make scheduling risk hard to spot.',
    questions: ['Which clinics are overbooked?', 'Where are no-shows increasing?'],
    output: 'Capacity exceptions and trend summary.',
  },
  {
    title: 'Retail',
    problem: 'Store spreadsheets hide category and margin movement.',
    questions: ['Which categories are slowing down?', 'What stores have margin risk?'],
    output: 'Store and category performance brief.',
  },
]

function formatDate(value) {
  if (!value) return 'Today'
  try {
    return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return 'Recent'
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 MB'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function getDatasetName(dataset) {
  return dataset?.display_name || dataset?.filename || dataset?.name || 'Untitled dataset'
}

function DashboardCard({ children, className = '' }) {
  return <section className={`app-card ${className}`.trim()}>{children}</section>
}

function SectionHeader({ eyebrow, title, action }) {
  return (
    <div className="app-section-header">
      <div>
        {eyebrow && <span>{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  )
}

function UsageMeter({ label, value, limit, tone = 'brand' }) {
  const safeLimit = Math.max(limit || 1, 1)
  const percent = Math.min(Math.round(((value || 0) / safeLimit) * 100), 100)
  return (
    <div className="usage-meter">
      <div>
        <span>{label}</span>
        <strong>{value || 0}/{safeLimit}</strong>
      </div>
      <div className="usage-track">
        <i className={`usage-fill usage-fill-${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

export default function DashboardHome() {
  const {
    files,
    datasetsList,
    historyMessages,
    historyTotal,
    reports,
    sessions,
    loadHistory,
    loadReports,
    loadDatasets,
    loadSessions,
    trackEvent,
  } = useDataPilot()
  const { user, isGuest, guestUsage, guestLimits } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    loadHistory?.()
    loadReports?.()
    loadDatasets?.({ archived: 'all' })
    loadSessions?.(true)
  }, [])

  const activeDatasets = useMemo(() => {
    const source = datasetsList?.length ? datasetsList : files
    return (source || []).filter((item) => !item.archived)
  }, [datasetsList, files])

  const recentDatasets = activeDatasets.slice(0, 4)
  const recentReports = (reports || []).slice(0, 3)
  const recentConversations = (sessions || historyMessages || []).slice(0, 3)
  const queryCount = historyTotal || historyMessages?.length || guestUsage?.query_count || 0
  const reportCount = reports?.length || guestUsage?.report_count || 0
  const storageBytes = activeDatasets.reduce((sum, dataset) => sum + (dataset.file_size_bytes || dataset.size || 0), 0)

  const onboarding = [
    { label: 'Upload Dataset', complete: activeDatasets.length > 0, to: '/app/datasets' },
    { label: 'Ask First Question', complete: queryCount > 0, to: '/app/analyze' },
    { label: 'Generate Chart', complete: historyMessages?.some((message) => message.chart_data), to: '/app/dashboard' },
    { label: 'Generate Report', complete: reportCount > 0, to: '/app/report' },
    { label: 'Complete Profile', complete: Boolean(user?.full_name || user?.email), to: '/app/settings/profile' },
  ]
  const completed = onboarding.filter((item) => item.complete).length
  const progress = Math.round((completed / onboarding.length) * 100)

  const handlePrompt = (prompt) => {
    trackEvent?.('DASHBOARD_PROMPT_CLICK', prompt)
    navigate('/app/analyze', { state: { suggestedPrompt: prompt } })
  }

  return (
    <div className="app-dashboard-shell" data-testid="premium-dashboard">
      <header className="app-dashboard-topbar">
        <div>
          <span className="app-eyebrow">Workspace</span>
          <h1>Welcome back, {user?.full_name || user?.email || (isGuest ? 'Guest analyst' : 'Explorer')}</h1>
          <p>Upload a spreadsheet, ask a question, generate reports, and keep your analysis moving.</p>
        </div>
        <div className="app-topbar-actions" aria-label="Dashboard utilities">
          <label className="app-search">
            <span className="sr-only">Search workspace</span>
            <input type="search" placeholder="Search datasets, reports, prompts..." />
          </label>
          <button type="button" className="app-icon-button" aria-label="Notifications future-ready">
            Alerts
          </button>
        </div>
      </header>

      <section className="app-hero-panel">
        <div>
          <span className="app-eyebrow">Next best action</span>
          <h2>Start with your spreadsheet. DataPilot handles the analysis loop.</h2>
          <p>
            Upload a CSV or Excel file, ask a plain-English question, review the result, inspect SQL,
            and turn the answer into a report.
          </p>
          <div className="app-hero-actions">
            <Link to="/app/datasets" className="btn-primary">Upload Dataset</Link>
            <Link to="/demo" className="btn-secondary">Try Demo Dataset</Link>
            <Link to="/app/analyze" className="btn-ghost">Continue Previous Analysis</Link>
          </div>
        </div>
        <div className="app-hero-preview" aria-label="Workspace flow preview">
          {['Upload', 'Ask', 'Visualize', 'Explain', 'Export'].map((item, index) => (
            <span key={item} className={index <= 2 ? 'is-active' : ''}>{item}</span>
          ))}
        </div>
      </section>

      <section className="quick-action-grid" aria-label="Quick actions">
        {[
          ['Upload Dataset', '/app/datasets', 'Add CSV or Excel files.'],
          ['New Analysis', '/app/analyze', 'Ask questions in chat.'],
          ['Generate Report', '/app/report', 'Create a narrative report.'],
          ['Browse Templates', '/app/templates', 'Start from a workflow.'],
          ['Invite Members', '/app/settings/members', 'Future-ready team setup.'],
        ].map(([title, to, desc]) => (
          <Link key={title} to={to} className="quick-action-card">
            <strong>{title}</strong>
            <span>{desc}</span>
          </Link>
        ))}
      </section>

      <div className="dashboard-main-grid">
        <div className="dashboard-primary-column">
          <DashboardCard>
            <SectionHeader title="Recent Datasets" eyebrow="Data" action={<Link to="/app/datasets">View all</Link>} />
            {recentDatasets.length ? (
              <div className="resource-list">
                {recentDatasets.map((dataset, index) => (
                  <article key={dataset.dataset_id || dataset.file_id || index} className="resource-row">
                    <div>
                      <strong>{getDatasetName(dataset)}</strong>
                      <span>{dataset.file_type || dataset.type || 'Spreadsheet'} · {(dataset.row_count || 0).toLocaleString()} rows · {dataset.column_count || 0} columns</span>
                      <small>{dataset.sheet_count || 1} sheets · {formatBytes(dataset.file_size_bytes)} · Uploaded {formatDate(dataset.upload_date || dataset.created_at)}</small>
                    </div>
                    <div className="row-actions">
                      <button type="button" aria-label={`Favorite ${getDatasetName(dataset)}`}>Favorite</button>
                      <Link to="/app/datasets">Open</Link>
                      <button type="button" aria-label={`Delete ${getDatasetName(dataset)}`}>Delete</button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="premium-empty-state">
                <span>No Dataset</span>
                <h3>Upload your first spreadsheet.</h3>
                <p>CSV and Excel files appear here with rows, columns, sheets, size, and upload time.</p>
                <Link to="/app/datasets" className="btn-primary">Upload Dataset</Link>
              </div>
            )}
          </DashboardCard>

          <DashboardCard>
            <SectionHeader title="Suggested Questions" eyebrow="Prompts" />
            <div className="prompt-grid">
              {suggestedQuestions.map((prompt) => (
                <button key={prompt} type="button" onClick={() => handlePrompt(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </DashboardCard>

          <DashboardCard>
            <SectionHeader title="Recent Reports" eyebrow="Reports" action={<Link to="/app/reports">View all</Link>} />
            {recentReports.length ? (
              <div className="report-grid">
                {recentReports.map((report) => (
                  <article key={report.report_id} className="report-card-mini">
                    <strong>{report.title}</strong>
                    <span>Created {formatDate(report.created_at)}</span>
                    <p>{report.description || 'Report preview ready for review.'}</p>
                    <div>
                      <Link to="/app/reports">Open</Link>
                      <button type="button">Export</button>
                      <button type="button">Duplicate</button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="premium-empty-state compact">
                <span>No Reports</span>
                <h3>Generate your first executive report.</h3>
                <Link to="/app/report" className="btn-secondary">Generate Report</Link>
              </div>
            )}
          </DashboardCard>

          <DashboardCard>
            <SectionHeader title="Premium Templates" eyebrow="Workflow starters" action={<Link to="/app/templates">Browse all</Link>} />
            <div className="template-grid">
              {templates.map((template) => (
                <article key={template.title} className="template-card">
                  <h3>{template.title}</h3>
                  <p><strong>Problem:</strong> {template.problem}</p>
                  <p><strong>Questions:</strong> {template.questions.join(' · ')}</p>
                  <p><strong>Output:</strong> {template.output}</p>
                </article>
              ))}
            </div>
          </DashboardCard>
        </div>

        <aside className="dashboard-side-column">
          <DashboardCard>
            <SectionHeader title="Usage" eyebrow={isGuest ? 'Guest plan' : 'Current plan'} action={<Link to="/app/billing">Manage</Link>} />
            <UsageMeter label="Storage" value={Math.round(storageBytes / 1024 / 1024)} limit={isGuest ? 5 : 1024} />
            <UsageMeter label="Queries" value={queryCount} limit={guestLimits?.query_count || 200} tone="sky" />
            <UsageMeter label="Reports" value={reportCount} limit={guestLimits?.report_count || 20} tone="emerald" />
            <Link to="/app/billing" className="upgrade-cta">Review plan and usage</Link>
          </DashboardCard>

          <DashboardCard>
            <SectionHeader title="Onboarding Progress" eyebrow={`${progress}% complete`} />
            <div className="progress-ring" style={{ '--progress': `${progress}%` }}>
              <strong>{completed}/{onboarding.length}</strong>
              <span>steps complete</span>
            </div>
            <div className="onboarding-list">
              {onboarding.map((item, index) => (
                <Link key={item.label} to={item.to} className={item.complete ? 'is-complete' : ''}>
                  <span>{item.complete ? 'Done' : index + 1}</span>
                  {item.label}
                </Link>
              ))}
            </div>
          </DashboardCard>

          <DashboardCard>
            <SectionHeader title="Recent Conversations" eyebrow="Continue" action={<Link to="/app/history">History</Link>} />
            {recentConversations.length ? (
              <div className="conversation-list">
                {recentConversations.map((conversation, index) => (
                  <Link key={conversation.session_id || conversation.id || index} to="/app/analyze">
                    <strong>{conversation.title || conversation.prompt || conversation.content || `Analysis ${index + 1}`}</strong>
                    <span>{formatDate(conversation.created_at || conversation.timestamp)}</span>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="premium-empty-state compact">
                <span>No Chat</span>
                <h3>Ask your first question.</h3>
                <Link to="/app/analyze" className="btn-secondary">Open Chat</Link>
              </div>
            )}
          </DashboardCard>
        </aside>
      </div>
    </div>
  )
}
