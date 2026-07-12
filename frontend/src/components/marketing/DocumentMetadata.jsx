import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

const SITE_URL = import.meta.env.VITE_PUBLIC_SITE_URL || 'http://localhost:5173'

export default function DocumentMetadata({ title, description, noindex = false }) {
  const location = useLocation()

  useEffect(() => {
    // 1. Set Title
    document.title = title ? `${title} | DataPilot` : 'DataPilot'

    // 2. Set Description
    let metaDescription = document.querySelector('meta[name="description"]')
    if (!metaDescription) {
      metaDescription = document.createElement('meta')
      metaDescription.setAttribute('name', 'description')
      document.head.appendChild(metaDescription)
    }
    metaDescription.setAttribute('content', description || 'Conversational spreadsheet analytics for CSV and Excel files.')

    // 3. Set Canonical Link
    let canonical = document.querySelector('link[rel="canonical"]')
    if (!canonical) {
      canonical = document.createElement('link')
      canonical.setAttribute('rel', 'canonical')
      document.head.appendChild(canonical)
    }
    canonical.setAttribute('href', `${SITE_URL}${location.pathname}`)

    // 4. Set Open Graph URL
    let ogUrl = document.querySelector('meta[property="og:url"]')
    if (!ogUrl) {
      ogUrl = document.createElement('meta')
      ogUrl.setAttribute('property', 'og:url')
      document.head.appendChild(ogUrl)
    }
    ogUrl.setAttribute('content', `${SITE_URL}${location.pathname}`)

    // 5. Set Open Graph Title
    let ogTitle = document.querySelector('meta[property="og:title"]')
    if (!ogTitle) {
      ogTitle = document.createElement('meta')
      ogTitle.setAttribute('property', 'og:title')
      document.head.appendChild(ogTitle)
    }
    ogTitle.setAttribute('content', title || 'DataPilot')

    // 6. Set Open Graph Description
    let ogDesc = document.querySelector('meta[property="og:description"]')
    if (!ogDesc) {
      ogDesc = document.createElement('meta')
      ogDesc.setAttribute('property', 'og:description')
      document.head.appendChild(ogDesc)
    }
    ogDesc.setAttribute('content', description || 'Conversational spreadsheet analytics.')

    // 7. Set Robots Indexing
    let robots = document.querySelector('meta[name="robots"]')
    if (!robots) {
      robots = document.createElement('meta')
      robots.setAttribute('name', 'robots')
      document.head.appendChild(robots)
    }
    robots.setAttribute('content', noindex ? 'noindex, nofollow' : 'index, follow')

  }, [title, description, noindex, location.pathname])

  return null
}
