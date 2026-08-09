import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const distDir = fileURLToPath(new URL('../dist', import.meta.url))

if (!existsSync(distDir)) {
  console.error('dist directory is missing. Run npm run build before this check.')
  process.exit(1)
}

const forbidden = [
  /https?:\/\/localhost(?::8000|:8001)\b/i,
  /https?:\/\/127\.0\.0\.1(?::8000|:8001)\b/i,
  /https?:\/\/0\.0\.0\.0(?::8000|:8001)\b/i,
  /https?:\/\/\[::1\](?::8000|:8001)\b/i,
]

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      yield* walk(path)
    } else if (/\.(html|js|css)$/.test(entry.name)) {
      yield path
    }
  }
}

const offenders = []
for (const file of walk(distDir)) {
  const text = readFileSync(file, 'utf8')
  if (forbidden.some((pattern) => pattern.test(text))) {
    offenders.push(file)
  }
}

if (offenders.length) {
  console.error('Production bundle contains a loopback API origin:')
  for (const file of offenders) console.error(`- ${file}`)
  process.exit(1)
}

console.log('Production API bundle check passed.')
