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
        <div className="flex items-center gap-2 select-none">
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

// ── Main ExplainPanel component ───────────────────────────────────────────────
export default function ExplainPanel({ metadata }) {
  const [expanded, setExpanded] = useState(false)
  const explain = metadata?.explain

  // Backwards-compat: still show SQL panel if exists in metadata
  const legacySql = metadata?.sql && !explain

  if (!explain && !legacySql) return null

  const type = explain?.type
  const sections = explain?.sections || []
  const sql = explain?.sql || metadata?.sql

  // If collapsed, display the "Show How This Was Calculated" button as requested
  if (!expanded) {
    return (
      <div className="mt-2.5 px-0.5 flex">
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-[10.5px] font-bold bg-brand-500/10 border border-brand-500/20 hover:bg-brand-500/20 hover:border-brand-500/35 text-brand-300 transition-all duration-300 shadow-sm hover:shadow-brand-500/10 select-none"
        >
          💡 Show How This Was Calculated
        </button>
      </div>
    )
  }

  // Expanded View - Redesigned premium Explainability Dashboard Card
  const typeConfig = {
    sql: { accent: 'brand' },
    forecast: { accent: 'violet' },
    chart: { accent: 'sky' },
  }
  const cfg = typeConfig[type] || { accent: 'brand' }

  const accentMap = {
    brand: { header: 'text-brand-400', border: 'border-brand-500/20', dot: 'bg-brand-500' },
    violet: { header: 'text-violet-400', border: 'border-violet-500/20', dot: 'bg-violet-500' },
    sky: { header: 'text-sky-400', border: 'border-sky-500/20', dot: 'bg-sky-500' },
  }
  const accent = accentMap[cfg.accent] || accentMap.brand

  return (
    <div className="mt-2.5 rounded-2xl border border-white/5 bg-white/[0.01] overflow-hidden text-[11px] animate-fade-in shadow-lg">
      {/* Top Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.04] bg-white/[0.01] select-none">
        <div className="flex items-center gap-2.5">
          <div className={`w-1.5 h-1.5 rounded-full ${accent.dot} opacity-80`} />
          <span className="font-bold text-slate-200 uppercase tracking-wider text-[9.5px] flex items-center gap-1.5">
            🔍 Calculation Breakdown & Rationale
          </span>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="text-slate-500 hover:text-slate-300 text-[10px] transition-colors"
        >
          Hide Breakdown ✕
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Overview Metrics Grid (Feature 4 mandatory fields) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5 bg-black/20 border border-white/[0.03] p-3 rounded-xl select-none">
          <div className="flex flex-col">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Data Source</span>
            <span className="text-[11px] font-bold text-slate-300 truncate mt-0.5" title={explain.data_source || 'N/A'}>
              {explain.data_source || 'N/A'}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Active Sheet</span>
            <span className="text-[11px] font-bold text-slate-300 mt-0.5">
              {explain.sheet || 'N/A'}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Confidence Score</span>
            <span className={`text-[11px] font-extrabold mt-0.5 ${
              (explain.confidence_score || 0) > 0.90 ? 'text-emerald-400' : 'text-amber-400'
            }`}>
              {Math.round((explain.confidence_score || 0.90) * 100)}%
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Filters Applied</span>
            <span className="text-[10px] font-bold text-slate-400 truncate mt-0.5" title={explain.filters || 'None'}>
              {explain.filters || 'None'}
            </span>
          </div>
        </div>

        {/* Reasoning Summary Section */}
        {explain.reasoning_summary && (
          <div className="bg-white/[0.01] border border-white/5 p-3 rounded-xl leading-relaxed">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider block mb-1 select-none">Reasoning Summary</span>
            <p className="text-slate-300 font-medium leading-relaxed">{explain.reasoning_summary}</p>
          </div>
        )}

        {/* Columns Used Section */}
        {Array.isArray(explain.columns) && explain.columns.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider mr-1 select-none">Columns Used:</span>
            {explain.columns.map(col => (
              <span key={col} className="bg-white/5 border border-white/5 px-2 py-0.5 rounded-lg text-[9.5px] font-semibold text-slate-400">
                {col}
              </span>
            ))}
          </div>
        )}

        {/* SQL Block if exists */}
        {sql && sql !== 'N/A' && (
          <div className="space-y-1.5">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider block select-none">SQL Generated</span>
            <SQLCodeBlock sql={sql} />
          </div>
        )}

        {/* Intermediate Calculations Section */}
        {Array.isArray(explain.intermediate_calculations) && explain.intermediate_calculations.length > 0 && (
          <div className="bg-white/[0.01] border border-white/5 p-3.5 rounded-xl space-y-2">
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider block select-none">Intermediate Calculations</span>
            <ul className="space-y-1.5 list-disc list-inside text-slate-300">
              {explain.intermediate_calculations.map((calc, i) => (
                <li key={i} className="font-mono text-[10px] leading-relaxed">
                  {calc}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Detailed Sections if any */}
        {sections.length > 0 && (
          <div className="border border-white/5 rounded-xl divide-y divide-white/[0.04] overflow-hidden">
            {sections.map((section, idx) => (
              <div key={idx} className="p-3 hover:bg-white/[0.01] transition-colors">
                <div className="flex items-center gap-2 mb-1.5 select-none">
                  <span className="text-sm leading-none">{section.icon}</span>
                  <span className="text-[8.5px] font-bold uppercase tracking-wider text-slate-400">
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
      </div>

      {/* Trust Footer */}
      <div className="flex items-center gap-2 px-4 py-2 border-t border-white/[0.04] bg-white/[0.01] text-[9px] text-slate-600 font-semibold select-none">
        <span>🔒</span>
        <span>Explainability calculations generated deterministically — 100% transparent audit log</span>
      </div>
    </div>
  )
}
