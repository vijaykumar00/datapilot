import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { publicSitemapRoutes } from '../src/data/marketing.js'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const outputPath = resolve(repoRoot, 'public', 'sitemap.xml')
const robotsPath = resolve(repoRoot, 'public', 'robots.txt')
const configuredSiteUrl = (process.env.VITE_PUBLIC_SITE_URL || 'http://localhost:5173').replace(/\/+$/, '')

function escapeXml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

export function generateSitemapXml(siteUrl = configuredSiteUrl, routes = publicSitemapRoutes) {
  const baseUrl = siteUrl.replace(/\/+$/, '')
  const urls = routes
    .filter((route) => !route.startsWith('/app') && !route.startsWith('/login') && !route.startsWith('/signup'))
    .map((route) => {
      const path = route === '/' ? '/' : route
      return `  <url><loc>${escapeXml(`${baseUrl}${path}`)}</loc></url>`
    })
    .join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`
}

export function generateRobotsTxt(siteUrl = configuredSiteUrl) {
  const baseUrl = siteUrl.replace(/\/+$/, '')
  return `User-agent: *\nAllow: /\nDisallow: /app/\nDisallow: /onboarding\nDisallow: /login\nDisallow: /signup\nDisallow: /forgot-password\n\nSitemap: ${baseUrl}/sitemap.xml\n`
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const xml = generateSitemapXml()
  const robots = generateRobotsTxt()
  await mkdir(dirname(outputPath), { recursive: true })
  await writeFile(outputPath, xml, 'utf8')
  await writeFile(robotsPath, robots, 'utf8')
  console.log(`Generated sitemap.xml with ${publicSitemapRoutes.length} public routes for ${configuredSiteUrl}`)
}
