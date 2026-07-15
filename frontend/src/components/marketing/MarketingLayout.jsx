import MarketingHeader from './MarketingHeader'
import MarketingFooter from './MarketingFooter'

export default function MarketingLayout({ children }) {
  return (
    <div className="marketing-shell noise">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <MarketingHeader />
      <main id="main-content" tabIndex="-1" className="marketing-main">
        {children}
      </main>
      <MarketingFooter />
    </div>
  )
}
