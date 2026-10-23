import { useEffect, useMemo, useRef, useState } from 'react'
import createPlotlyComponent from 'react-plotly.js/factory'
// Cartesian bundle (~1.3 MB vs ~4.6 MB): bar, box, heatmap, histogram, pie,
// scatter, contour, violin — every trace type the backend produces.
import Plotly from 'plotly.js-cartesian-dist-min'
import { useTheme } from '../lib/theme'

const Plot = createPlotlyComponent(Plotly)

// Charts saved by older versions may use WebGL scatter, which this bundle omits.
const TRACE_FALLBACKS = { scattergl: 'scatter' }
function normalizeTraces(data = []) {
  return data.map(trace => (
    trace && TRACE_FALLBACKS[trace.type] ? { ...trace, type: TRACE_FALLBACKS[trace.type] } : trace
  ))
}

const FONT_FAMILY = "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif"
const NARROW_WIDTH = 520

// Design tokens hold "R G B" triplets; Plotly needs a CSS colour string.
function token(name, fallback) {
  if (typeof document === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw ? `rgb(${raw.split(/\s+/).join(',')})` : fallback
}

// `dark` is the resolved theme; it is part of the result so the palette is
// recomputed (and Plotly re-rendered) whenever the theme flips.
function readPalette(dark) {
  return {
    dark,
    fg: token('--c-fg', dark ? 'rgb(230,233,238)' : 'rgb(22,27,34)'),
    muted: token('--c-muted', dark ? 'rgb(160,170,184)' : 'rgb(79,89,102)'),
    line: token('--c-line', dark ? 'rgb(45,52,64)' : 'rgb(216,221,227)'),
    lineStrong: token('--c-line-strong', dark ? 'rgb(70,79,94)' : 'rgb(185,193,203)'),
    elevated: token('--c-elevated', dark ? 'rgb(27,32,41)' : 'rgb(255,255,255)'),
    colorway: [1, 2, 3, 4, 5, 6].map(i => token(`--c-chart-${i}`, null)).filter(Boolean),
  }
}

// Plotly accepts a title as a string or an object; normalise to an object.
function asTitle(title) {
  if (title == null || title === '') return undefined
  return typeof title === 'string' ? { text: title } : title
}

function titleText(title) {
  if (!title) return ''
  return typeof title === 'string' ? title : title.text || ''
}

// Theme an axis: the spec's own title text, ranges and tick settings win;
// grid, line and font colours come from the theme.
function themeAxis(axis = {}, p) {
  const title = asTitle(axis.title)
  return {
    automargin: true,
    ...axis,
    gridcolor: p.line,
    linecolor: p.lineStrong,
    zerolinecolor: p.lineStrong,
    tickfont: { ...axis.tickfont, family: FONT_FAMILY, color: p.muted, size: 12 },
    ...(title ? { title: { ...title, font: { ...title.font, family: FONT_FAMILY, color: p.muted, size: 13 } } } : {}),
  }
}

function buildLayout(layout = {}, p, narrow) {
  const merged = { ...layout }

  // Every axis key (xaxis, xaxis2, yaxis, ...) gets themed colours.
  const axisKeys = Object.keys(layout).filter(k => /^[xy]axis\d*$/.test(k))
  if (!axisKeys.includes('xaxis')) axisKeys.push('xaxis')
  if (!axisKeys.includes('yaxis')) axisKeys.push('yaxis')
  axisKeys.forEach(k => { merged[k] = themeAxis(layout[k], p) })

  const title = asTitle(layout.title)
  if (title) {
    merged.title = {
      x: 0.01,
      xanchor: 'left',
      ...title,
      font: { ...title.font, family: FONT_FAMILY, color: p.fg, size: 15 },
    }
  }

  const userLegend = layout.legend || {}
  merged.legend = {
    ...userLegend,
    ...(narrow ? { orientation: 'h', x: 0, xanchor: 'left', y: -0.25, yanchor: 'top' } : {}),
    bgcolor: 'rgba(0,0,0,0)',
    font: { ...userLegend.font, family: FONT_FAMILY, color: p.muted, size: 12 },
  }

  const defaultMargin = narrow
    ? { l: 44, r: 12, t: title ? 48 : 16, b: 40 }
    : { l: 56, r: 20, t: title ? 52 : 20, b: 48 }

  return {
    ...merged,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { ...layout.font, family: FONT_FAMILY, color: p.muted, size: 12 },
    ...(p.colorway.length ? { colorway: p.colorway } : {}),
    margin: layout.margin || defaultMargin,
    autosize: true,
    hoverlabel: {
      ...layout.hoverlabel,
      bgcolor: p.elevated,
      bordercolor: p.line,
      font: { family: FONT_FAMILY, color: p.fg, size: 13 },
    },
    modebar: { bgcolor: 'rgba(0,0,0,0)', color: p.muted, activecolor: p.fg },
  }
}

const PLOT_CONFIG = {
  displayModeBar: true,
  // Keep zoom, pan, reset and "Download plot as a png"; drop the rarely used tools.
  modeBarButtonsToRemove: [
    'select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines',
    'hoverClosestCartesian', 'hoverCompareCartesian',
  ],
  displaylogo: false,
  responsive: true,
  toImageButtonOptions: {
    format: 'png',
    filename: 'datapilot_chart',
    height: 600,
    width: 1000,
    scale: 2,
  },
}

export default function ChartRenderer({ spec, onDataPointClick }) {
  const plotRef = useRef(null)
  const containerRef = useRef(null)
  const { theme } = useTheme()
  const [narrow, setNarrow] = useState(false)

  // Track the container width so the legend can move below the plot on phones.
  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect?.width || 0
      setNarrow(width > 0 && width < NARROW_WIDTH)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [spec])

  // The `dark` class on <html> decides which token set is active; useTheme()
  // re-renders this component whenever it changes.
  const isDark = theme === 'dark'
    || (typeof document !== 'undefined' && document.documentElement.classList.contains('dark'))
  const palette = useMemo(() => readPalette(isDark), [isDark])

  const layout = spec?.layout
  const rawData = spec?.data
  const mergedLayout = useMemo(() => buildLayout(layout, palette, narrow), [layout, palette, narrow])
  const data = useMemo(() => normalizeTraces(rawData), [rawData])

  if (!spec) return null

  const chartTitle = titleText(layout?.title)

  const handleClick = (event) => {
    if (!onDataPointClick) return
    const point = event.points?.[0]
    if (point) {
      onDataPointClick({ x: point.x, y: point.y, label: point.label, text: point.text })
    }
  }

  return (
    <figure
      id="chart-container"
      ref={containerRef}
      aria-label={chartTitle ? `Chart: ${chartTitle}` : 'Chart'}
      className="m-0 min-w-0 overflow-hidden rounded-lg border border-line bg-surface"
    >
      <Plot
        ref={plotRef}
        data={data}
        layout={mergedLayout}
        config={PLOT_CONFIG}
        onClick={handleClick}
        style={{ width: '100%', minHeight: '340px' }}
        useResizeHandler
      />
      {chartTitle && <figcaption className="sr-only">{chartTitle}</figcaption>}
    </figure>
  )
}
