import { useRef } from 'react'
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'

// Create Plot component from the min bundle (avoids plotly.js/dist/plotly resolution issue)
const Plot = createPlotlyComponent(Plotly)

export default function ChartRenderer({ spec, onDataPointClick }) {
  const plotRef = useRef(null)

  if (!spec) return null

  const { data, layout } = spec

  const mergedLayout = {
    ...layout,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter, sans-serif', color: '#94a3b8', size: 12 },
    xaxis: {
      ...layout?.xaxis,
      gridcolor: 'rgba(255,255,255,0.05)',
      linecolor: 'rgba(255,255,255,0.08)',
      tickfont: { color: '#64748b', size: 11 },
      title: { ...layout?.xaxis?.title, font: { color: '#94a3b8' } },
    },
    yaxis: {
      ...layout?.yaxis,
      gridcolor: 'rgba(255,255,255,0.05)',
      linecolor: 'rgba(255,255,255,0.08)',
      tickfont: { color: '#64748b', size: 11 },
      title: { ...layout?.yaxis?.title, font: { color: '#94a3b8' } },
    },
    title: {
      ...layout?.title,
      font: { color: '#f1f5f9', size: 14, family: 'Inter, sans-serif' },
    },
    legend: {
      ...layout?.legend,
      font: { color: '#94a3b8', size: 11 },
      bgcolor: 'rgba(0,0,0,0)',
    },
    margin: layout?.margin || { l: 50, r: 20, t: 50, b: 50 },
    autosize: true,
    hoverlabel: {
      bgcolor: '#1e293b',
      bordercolor: 'rgba(99,102,241,0.4)',
      font: { color: '#f1f5f9', family: 'Inter, sans-serif', size: 12 },
    },
  }

  const mergedConfig = {
    displayModeBar: true,
    modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
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

  const handleClick = (event) => {
    if (!onDataPointClick) return
    const point = event.points?.[0]
    if (point) {
      onDataPointClick({ x: point.x, y: point.y, label: point.label, text: point.text })
    }
  }

  return (
    <div
      id="chart-container"
      className="glass rounded-2xl overflow-hidden border border-white/8 animate-slide-up"
    >
      <Plot
        ref={plotRef}
        data={data}
        layout={mergedLayout}
        config={mergedConfig}
        onClick={handleClick}
        style={{ width: '100%', minHeight: '340px' }}
        useResizeHandler
      />
    </div>
  )
}
