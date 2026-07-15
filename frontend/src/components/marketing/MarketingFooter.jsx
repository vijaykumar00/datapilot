import { Link } from 'react-router-dom'
import { legalNavItems } from '../../data/marketing'
import BrandLogo from './BrandLogo'

const productLinks = [
  { label: 'Features', path: '/features' },
  { label: 'Use Cases', path: '/use-cases' },
  { label: 'Security', path: '/security' },
  { label: 'Pricing', path: '/pricing' },
]

const resourceLinks = [
  { label: 'Documentation', path: '/docs' },
  { label: 'About', path: '/about' },
  { label: 'Contact', path: '/contact' },
]

function FooterColumn({ title, links }) {
  return (
    <div className="footer-column">
      <h2>{title}</h2>
      {links.map((link) => (
        <Link key={link.path} to={link.path}>
          {link.label}
        </Link>
      ))}
    </div>
  )
}

export default function MarketingFooter() {
  return (
    <footer className="marketing-footer">
      <div className="marketing-footer-inner">
        <div className="footer-brand">
          <BrandLogo />
          <p>
            Conversational analytics, data profiling, and report-ready outputs for CSV and Excel workflows.
          </p>
        </div>

        <FooterColumn title="Product" links={productLinks} />
        <FooterColumn title="Resources" links={resourceLinks} />
        <FooterColumn title="Legal" links={legalNavItems} />
      </div>

      <div className="marketing-footer-bottom">
        <span>Copyright 2026 DataPilot. Draft legal pages require professional review before production launch.</span>
      </div>
    </footer>
  )
}
