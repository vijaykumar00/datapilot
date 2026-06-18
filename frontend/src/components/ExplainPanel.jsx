import { useState } from 'react'

// ── SQL Clause colors ─────────────────────────────────────────────────────────
const CLAUSE_COLORS = {
  SELECT: 'text-violet-400',
  FROM: 'text-emerald-400',
  WHERE: 'text-amber-400',
  GROUP: 'text-sky-400',
  ORDER: 'text-teal-400',
  LIMIT: 'text-rose-400',
  JOIN: 'text-orange-400',
}

function highlightSQL(sql) {
  if (!sql) return sql
  const keywords = ['SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'LIMIT',
    'JOIN', 'LEFT JOIN', 'INNER JOIN', 'AS', 'ON', 'AND', 'OR', 'NOT',
    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'DISTINCT', 'DESC', 'ASC', 'HAVING']
  let result = sql
  keywords.forEach(kw => {
    const colorClass = CLAUSE_COLORS[kw.split(' ')[0]] || 'text-brand-300'
    result = result.replace(
      new RegExp(`\\b(${kw})\\b`, 'gi'),
      `<span class="${colorClass} font-bold">$1</span>`
    )
  })
  // Highlight strings in quotes
  result = result.replace(/'([^']+)'/g, "<span class='text-amber-300'>'$1'</span>")
  // Highlight numbers
  result = result.replace(/\b(\d+)\b/g, "<span class='text-emerald-300'>$1</span>")
  return result
}

// ── Section content renderer ──────────────────────────────────────────────────
function SectionContent({ content }) {
  if (Array.isArray(content)) {
    return (
      <ul className="space-y-1">
        {content.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-[11px] text-slate-300 leading-snug">
            <span className="text-brand-500 mt-0.5 flex-shrink-0">▸</span>
            <span className="font-mono">{item}</span>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <p className="text-[11px] text-slate-300 leading-relaxed font-mono">{content}</p>
  )
}

// ── SQL specific panel with syntax highlighted code ───────────────────────────
function SQLCodeBlock({ sql }) {
  const [copied, setCopied] = useState(false)
  if (!sql) return null
  const lines = sql.split('\n')
  const lineNums = lines.map((_, i) => i + 1).join('\n')

  const handleCopy = () => {
    navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-xl overflow-hidden border border-white/5 bg-[#03060f]">
      <div className="flex items-center justify-between px-3.5 py-2 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-rose-500/70" />
          <span className="w-2 h-2 rounded-full bg-amber-500/70" />
          <span className="w-2 h-2 rounded-full bg-emerald-500/70" />
          <span className="text-[9px] text-slate-600 font-mono ml-1 uppercase tracking-widest">SQL Output</span>
        </div>
        <button
          onClick={handleCopy}
          className="text-[9px] bg-white/5 hover:bg-brand-500/20 text-slate-400 hover:text-brand-300 px-1.5 py-0.5 rounded border border-white/5 transition-all"
        >
          {copied ? 'Copied ✓' : 'Copy SQL'}
        </button>
      </div>
      <div className="flex overflow-x-auto custom-scrollbar max-h-40">
        <div className="text-[10px] text-slate-700 font-mono leading-5 px-3 py-2.5 text-right select-none border-r border-white/5 bg-white/[0.01] min-w-[2rem]">
          {lineNums}
        </div>
        <pre
          className="text-[10.5px] font-mono leading-5 px-3 py-2.5 text-slate-300 flex-1 overflow-x-auto"
          dangerouslySetInnerHTML={{ __html: highlightSQL(sql) }}
        />
      </div>
    </div>
  )
}

// ── Method badge for forecast ─────────────────────────────────────────────────
function MethodBadge({ sections }) {
  const methodSection = sections?.find(s => s.label === 'Method Selected')
  if (!methodSection) return null
  const isHW = Array.isArray(methodSection.content) &&
    methodSection.content[0]?.includes('Holt-Winters')

  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold border ${
      isHW
        ? 'bg-violet-500/10 border-violet-500/25 text-violet-300'
        : 'bg-amber-500/10 border-amber-500/25 text-amber-300'
    }`}>
      {isHW ? '📈 Holt-Winters' : '📉 Linear Regression'}
    </div>
  )
}

// ── Chart type badge ──────────────────────────────────────────────────────────
const CHART_ICONS = {
  bar: '📊', line: '📈', scatter: '⚡', histogram: '🔢',
  pie: '🥧', box: '📦', heatmap: '🌡️'
}

function ChartBadge({ chartType }) {
  if (!chartType) return null
  return (
    <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold border bg-sky-500/10 border-sky-500/25 text-sky-300">
      {CHART_ICONS[chartType] || '📊'} {chartType} chart
    </div>
  )
}

// ── Trend arrow indicator ─────────────────────────────────────────────────────
function TrendBadge({ sections }) {
  const trendSection = sections?.find(s => s.label === 'Detected Trend')
  if (!trendSection || typeof trendSection.content !== 'string') return null
  const isRising = trendSection.content.includes('Rising')
  const isDeclining = trendSection.content.includes('Declining')
  if (!isRising && !isDeclining) return null

  return (
    <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold border ${
      isRising
        ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
        : 'bg-rose-500/10 border-rose-500/25 text-rose-400'
    }`}>
      {isRising ? '⬆' : '⬇'} {isRising ? 'Rising' : 'Declining'}
    </div>
  )
}

// ── Main ExplainPanel component ───────────────────────────────────────────────
export default function ExplainPanel({ metadata }) {
  const [expanded, setExpanded] = useState(false)
  const explain = metadata?.explain

  // Backwards-compat: still show SQL panel even if no explain block
  const legacySql = metadata?.sql && !explain

  if (!explain && !legacySql) return null

  const type = explain?.type
  const sections = explain?.sections || []
  const sql = explain?.sql || metadata?.sql

  const typeConfig = {
    sql: { label: 'SQL Explainability', icon: '⚙️', accent: 'brand' },
    forecast: { label: 'Forecast Explainability', icon: '🔮', accent: 'violet' },
    chart: { label: 'Chart Explainability', icon: '📊', accent: 'sky' },
  }
  const cfg = typeConfig[type] || { label: 'AI Explainability', icon: '🔍', accent: 'brand' }

  const accentMap = {
    brand: { header: 'text-brand-400', badge: 'bg-brand-500/10 border-brand-500/20', dot: 'bg-brand-500' },
    violet: { header: 'text-violet-400', badge: 'bg-violet-500/10 border-violet-500/20', dot: 'bg-violet-500' },
    sky: { header: 'text-sky-400', badge: 'bg-sky-500/10 border-sky-500/20', dot: 'bg-sky-500' },
  }
  const accent = accentMap[cfg.accent] || accentMap.brand

  return (
    <div className="mt-1.5 rounded-xl border border-white/5 bg-white/[0.01] overflow-hidden text-[11px]">
      {/* Header toggle */}
      <button
        id={`explain-panel-${type || 'legacy'}`}
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-white/[0.02] transition-all focus:outline-none group"
      >
        <div className="flex items-center gap-2.5">
          <div className={`w-1.5 h-1.5 rounded-full ${accent.dot} opacity-80`} />
          <span className={`font-semibold ${accent.header} flex items-center gap-1.5`}>
            {cfg.icon} {cfg.label}
          </span>
          {/* Inline summary badges */}
          {type === 'forecast' && !expanded && (
            <div className="flex items-center gap-1.5 ml-1">
              <MethodBadge sections={sections} />
              <TrendBadge sections={sections} />
            </div>
          )}
          {type === 'chart' && !expanded && (
            <div className="flex items-center gap-1.5 ml-1">
              <ChartBadge chartType={explain?.chart_type} />
            </div>
          )}
          {type === 'sql' && !expanded && metadata?.row_count !== undefined && (
            <span className="text-[9px] bg-brand-500/10 text-brand-300 px-1.5 py-0.5 rounded border border-brand-500/20 font-mono">
              {metadata.row_count} rows
            </span>
          )}
        </div>
        <span className="text-slate-600 group-hover:text-slate-400 transition-colors text-[10px]">
          {expanded ? 'Hide ✕' : 'Expand ＋'}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-white/5 animate-fade-in">
          {/* SQL code block at the top for sql type */}
          {(type === 'sql' || legacySql) && sql && (
            <div className="p-3.5 pb-2">
              <SQLCodeBlock sql={sql} />
            </div>
          )}

          {/* Sections */}
          {sections.length > 0 && (
            <div className="grid grid-cols-1 gap-0 divide-y divide-white/[0.04]">
              {sections.map((section, idx) => (
                <div
                  key={idx}
                  className="px-4 py-3 hover:bg-white/[0.015] transition-colors"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-sm leading-none">{section.icon}</span>
                    <span className={`text-[9px] font-bold uppercase tracking-wider ${accent.header} opacity-90`}>
                      {section.label}
                    </span>
                  </div>
                  <div className="pl-5">
                    <SectionContent content={section.content} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Legacy SQL only (no explain block) */}
          {legacySql && !sections.length && (
            <div className="p-3.5 pt-2">
              {metadata.explanation && (
                <p className="text-[11px] text-slate-400 italic mb-2 px-1">{metadata.explanation}</p>
              )}
            </div>
          )}

          {/* Trust footer */}
          <div className="flex items-center gap-2 px-4 py-2.5 border-t border-white/[0.04] bg-white/[0.01]">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px]">🔒</span>
              <span className="text-[9px] text-slate-600 font-medium">
                Explainability data generated deterministically — no extra AI calls consumed
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
