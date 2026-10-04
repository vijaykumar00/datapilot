// Fails the build when the entry chunk (what every visitor downloads first) grows
// past the budget.  Route-level code splitting keeps marketing and workspace
// views, markdown rendering and Plotly out of it.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const BUDGET_KB = Number(process.env.ENTRY_CHUNK_BUDGET_KB || 450)
const dist = fileURLToPath(new URL('../dist', import.meta.url))
const html = readFileSync(join(dist, 'index.html'), 'utf8')
const entries = [...html.matchAll(/<script[^>]+src="\/?(assets\/[^"]+\.js)"/g)].map(m => m[1])
if (!entries.length) {
  console.error('No entry script found in dist/index.html')
  process.exit(1)
}
let failed = false
for (const entry of entries) {
  const kb = statSync(join(dist, entry)).size / 1024
  console.log(`${entry}: ${kb.toFixed(1)} kB (budget ${BUDGET_KB} kB)`)
  if (kb > BUDGET_KB) failed = true
}
const chunks = readdirSync(join(dist, 'assets')).filter(f => f.endsWith('.js'))
console.log(`${chunks.length} JS chunks emitted`)
if (failed) {
  console.error('Entry chunk exceeds the size budget. Lazy-load the new heavy import instead.')
  process.exit(1)
}
