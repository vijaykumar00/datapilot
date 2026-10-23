import { useState } from 'react'
import { Check, ChevronDown, Copy, ShieldCheck } from 'lucide-react'
import { cx } from './ui'

// SQL is produced by the model from user text, so it is escaped before any
// highlighting markup is added (never inject raw SQL as HTML).
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const KEYWORDS = ['SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'LIMIT', 'LEFT JOIN', 'INNER JOIN', 'JOIN', 'AS', 'ON',
  'AND', 'OR', 'NOT', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'DISTINCT', 'DESC', 'ASC', 'HAVING', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END']

export function highlightSQL(sql) {
  if (!sql) return ''
  let out = escapeHtml(sql)
  // strings and numbers first, then keywords (word-bounded, outside tags)
  out = out.replace(/'([^']*)'/g, '<span class="sql-str">\'$1\'</span>')
  out = out.replace(/(^|[^\w#;])(\d+(?:\.\d+)?)\b/g, '$1<span class="sql-num">$2</span>')
  const kw = new RegExp(`\\b(${KEYWORDS.map((k) => k.replace(' ', '\\s+')).join('|')})\\b(?![^<]*>)`, 'gi')
  out = out.replace(kw, '<span class="sql-kw">$1</span>')
  return out
}

export function SQLCodeBlock({ sql, label = 'SQL' }) {
  const [copied, setCopied] = useState(false)
  if (!sql) return null
  const lines = sql.split('\n')
  const handleCopy = () => {
    navigator.clipboard?.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }
  return (
    <div className="editor-block">
      <div className="editor-header">
        <span className="text-xs font-medium text-muted">{label}</span>
        <button type="button" onClick={handleCopy} className="btn-ghost btn-sm h-7 px-2" aria-label="Copy SQL">
          {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="editor-terminal max-h-60">
        <div className="editor-lines" aria-hidden="true">{lines.map((_, i) => <div key={i}>{i + 1}</div>)}</div>
        <pre className="editor-code m-0" dangerouslySetInnerHTML={{ __html: highlightSQL(sql) }} />
      </div>
    </div>
  )
}

function Fact({ label, children, title }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-subtle">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-medium text-fg" title={title}>{children}</dd>
    </div>
  )
}

function SectionContent({ content }) {
  if (Array.isArray(content)) {
    return (
      <ul className="list-disc space-y-1 pl-4 text-sm text-fg marker:text-subtle">
        {content.map((item, i) => <li key={i}>{String(item)}</li>)}
      </ul>
    )
  }
  return <p className="text-sm text-fg">{String(content)}</p>
}

/**
 * "How this was calculated": the data source, columns, filters, SQL and any
 * intermediate steps behind an AI answer.  Collapsed by default.
 */
export default function ExplainPanel({ metadata, defaultOpen = false, bare = false }) {
  const [expanded, setExpanded] = useState(defaultOpen)
  const explain = metadata?.explain
  const legacySql = metadata?.sql && !explain
  if (!explain && !legacySql) return null

  const sections = (explain?.sections || []).filter((s) => s && s.label)
  const sql = explain?.sql || metadata?.sql
  const hasConfidence = typeof explain?.confidence_score === 'number'

  const body = (
    <div className="space-y-4">
      {explain && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          <Fact label="Data source" title={explain.data_source}>{explain.data_source || 'Not recorded'}</Fact>
          <Fact label="Sheet">{explain.sheet || '—'}</Fact>
          {hasConfidence
            ? <Fact label="Confidence">{Math.round(explain.confidence_score * 100)}%</Fact>
            : <Fact label="Verification" title={explain.verification}>{explain.verification || 'Computed from your data'}</Fact>}
          <Fact label="Filters" title={explain.filters}>{explain.filters || 'None'}</Fact>
        </dl>
      )}
      {explain?.reasoning_summary && <p className="text-sm text-fg">{explain.reasoning_summary}</p>}
      {Array.isArray(explain?.columns) && explain.columns.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs text-subtle">Columns used</span>
          {explain.columns.map((col) => <span key={col} className="badge badge-neutral font-mono">{col}</span>)}
        </div>
      )}
      {sql && sql !== 'N/A' && <SQLCodeBlock sql={sql} label="SQL that produced this result" />}
      {Array.isArray(explain?.intermediate_calculations) && explain.intermediate_calculations.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-subtle">Intermediate calculations</p>
          <ul className="list-disc space-y-1 pl-4 font-mono text-xs text-fg marker:text-subtle">
            {explain.intermediate_calculations.map((calc, i) => <li key={i}>{calc}</li>)}
          </ul>
        </div>
      )}
      {sections.length > 0 && (
        <div className="divide-y divide-line rounded-md border border-line">
          {sections.map((section, idx) => (
            <div key={idx} className="p-3">
              <p className="mb-1 text-xs font-medium text-muted">{section.label}</p>
              <SectionContent content={section.content} />
            </div>
          ))}
        </div>
      )}
      <p className="flex items-center gap-1.5 text-xs text-subtle">
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
        Numbers come from running the query on your data, not from the AI model.
      </p>
    </div>
  )

  if (bare) return body

  return (
    <div className="rounded-md border border-line">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
      >
        How this was calculated
        <ChevronDown className={cx('h-4 w-4 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
      </button>
      {expanded && <div className="border-t border-line p-3 animate-fade-in">{body}</div>}
    </div>
  )
}
