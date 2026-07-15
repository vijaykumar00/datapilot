import { Badge, Button } from './MarketingPrimitives'

export default function PageHero({
  eyebrow,
  title,
  description,
  ctaLabel = 'Try free',
  ctaTo = '/signup',
  secondaryCtaLabel,
  secondaryCtaTo,
}) {
  return (
    <section className="marketing-hero">
      <div className="section-inner">
        {eyebrow && <Badge>{eyebrow}</Badge>}
        <h1>{title}</h1>
        <p>{description}</p>
        <div className="marketing-hero-actions">
          <Button to={ctaTo}>{ctaLabel}</Button>
          {secondaryCtaLabel && secondaryCtaTo && (
            <Button to={secondaryCtaTo} variant="secondary">
              {secondaryCtaLabel}
            </Button>
          )}
        </div>
      </div>
    </section>
  )
}
