import { Monitor, Moon, Sun } from 'lucide-react'
import { IconButton } from '../ui'
import { useTheme } from '../../lib/theme'

const THEME_ORDER = ['light', 'dark', 'system']
const THEME_META = {
  light: { icon: Sun, label: 'Light theme' },
  dark: { icon: Moon, label: 'Dark theme' },
  system: { icon: Monitor, label: 'Match system theme' },
}

export function ThemeToggle({ className }) {
  const { preference, setPreference } = useTheme()
  const meta = THEME_META[preference]
  const next = THEME_ORDER[(THEME_ORDER.indexOf(preference) + 1) % THEME_ORDER.length]
  return (
    <IconButton
      icon={meta.icon}
      label={`${meta.label} (switch to ${THEME_META[next].label.toLowerCase()})`}
      className={className}
      onClick={() => setPreference(next)}
    />
  )
}

