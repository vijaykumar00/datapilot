import SectionContainer from './SectionContainer'
import { Button } from './MarketingPrimitives'

export default function CTASection({
  title = 'Ready to analyze your spreadsheet data?',
  description = 'Create a workspace, upload a CSV or Excel file, and start asking questions in plain English.',
}) {
  return (
    <SectionContainer className="marketing-cta-band">
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <div className="marketing-cta-actions">
        <Button to="/try-free">Try free</Button>
        <Button to="/login" variant="ghost">Sign in</Button>
      </div>
    </SectionContainer>
  )
}
