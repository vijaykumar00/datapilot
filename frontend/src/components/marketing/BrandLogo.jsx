import { Link } from 'react-router-dom'
import { LogoMark, Wordmark } from '../ui/Logo'

export default function BrandLogo({ compact = false, className = '' }) {
  return (
    <Link to="/" className={`inline-flex items-center gap-2.5 rounded-md focus-ring ${className}`} aria-label="DataPilot home">
      <LogoMark size={30} />
      {!compact && <Wordmark />}
    </Link>
  )
}
