import assert from 'node:assert/strict'
import { test } from 'node:test'
import { publicSitemapRoutes } from '../src/data/marketing.js'
import { generateRobotsTxt, generateSitemapXml } from '../scripts/generate-sitemap.mjs'

test('local sitemap configuration generates localhost absolute URLs', () => {
  const xml = generateSitemapXml('http://localhost:5173')

  assert.match(xml, /<loc>http:\/\/localhost:5173\/<\/loc>/)
  assert.match(xml, /<loc>http:\/\/localhost:5173\/features<\/loc>/)
})

test('production sitemap configuration uses configured absolute origin', () => {
  const xml = generateSitemapXml('https://example.datapilot.test')

  assert.match(xml, /<loc>https:\/\/example\.datapilot\.test\/<\/loc>/)
  assert.match(xml, /<loc>https:\/\/example\.datapilot\.test\/legal\/privacy<\/loc>/)
  assert.doesNotMatch(xml, /localhost/)
})

test('sitemap includes public route config and excludes private routes', () => {
  const xml = generateSitemapXml('https://example.datapilot.test', [
    ...publicSitemapRoutes,
    '/app/analyze',
    '/login',
    '/signup',
  ])

  for (const route of publicSitemapRoutes) {
    assert.match(xml, new RegExp(`<loc>https://example\\.datapilot\\.test${route === '/' ? '/' : route}</loc>`))
  }

  assert.doesNotMatch(xml, /\/app\/analyze/)
  assert.doesNotMatch(xml, /\/login/)
  assert.doesNotMatch(xml, /\/signup/)
})

test('robots sitemap reference uses configured absolute site URL', () => {
  const robots = generateRobotsTxt('https://example.datapilot.test')

  assert.match(robots, /Sitemap: https:\/\/example\.datapilot\.test\/sitemap\.xml/)
  assert.match(robots, /Disallow: \/app\//)
})
