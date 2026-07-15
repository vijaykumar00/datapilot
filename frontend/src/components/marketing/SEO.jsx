import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { publicSiteUrl, siteConfig } from '../../data/marketing'

function ensureMeta(selector, create) {
  let node = document.head.querySelector(selector)
  if (!node) {
    node = create()
    document.head.appendChild(node)
  }
  return node
}

export function buildAbsoluteUrl(path = '/') {
  if (/^https?:\/\//i.test(path)) return path
  return `${publicSiteUrl}${path.startsWith('/') ? path : `/${path}`}`
}

export default function SEO({
  title,
  description,
  canonicalPath,
  image = siteConfig.ogImage,
  noindex = false,
}) {
  const location = useLocation()
  const pageTitle = title || siteConfig.defaultTitle
  const pageDescription = description || siteConfig.defaultDescription
  const canonicalUrl = buildAbsoluteUrl(canonicalPath || location.pathname)
  const imageUrl = buildAbsoluteUrl(image)

  useEffect(() => {
    document.title = pageTitle.includes(siteConfig.name) ? pageTitle : `${pageTitle} | ${siteConfig.name}`

    const descriptionMeta = ensureMeta('meta[name="description"]', () => {
      const node = document.createElement('meta')
      node.setAttribute('name', 'description')
      return node
    })
    descriptionMeta.setAttribute('content', pageDescription)

    const canonical = ensureMeta('link[rel="canonical"]', () => {
      const node = document.createElement('link')
      node.setAttribute('rel', 'canonical')
      return node
    })
    canonical.setAttribute('href', canonicalUrl)

    const robots = ensureMeta('meta[name="robots"]', () => {
      const node = document.createElement('meta')
      node.setAttribute('name', 'robots')
      return node
    })
    robots.setAttribute('content', noindex ? 'noindex, nofollow' : 'index, follow')

    const metaValues = {
      'meta[property="og:type"]': ['property', 'og:type', 'website'],
      'meta[property="og:site_name"]': ['property', 'og:site_name', siteConfig.name],
      'meta[property="og:title"]': ['property', 'og:title', pageTitle],
      'meta[property="og:description"]': ['property', 'og:description', pageDescription],
      'meta[property="og:image"]': ['property', 'og:image', imageUrl],
      'meta[property="og:url"]': ['property', 'og:url', canonicalUrl],
      'meta[name="twitter:card"]': ['name', 'twitter:card', 'summary_large_image'],
      'meta[name="twitter:title"]': ['name', 'twitter:title', pageTitle],
      'meta[name="twitter:description"]': ['name', 'twitter:description', pageDescription],
      'meta[name="twitter:image"]': ['name', 'twitter:image', imageUrl],
    }

    Object.entries(metaValues).forEach(([selector, [attrName, attrValue, content]]) => {
      const node = ensureMeta(selector, () => {
        const meta = document.createElement('meta')
        meta.setAttribute(attrName, attrValue)
        return meta
      })
      node.setAttribute('content', content)
    })
  }, [canonicalUrl, imageUrl, noindex, pageDescription, pageTitle])

  return null
}
