/** Workspace navigation and page titles (shared by the shell and the command palette). */
import { Bookmark, CreditCard, Database, FileText, Home, MessagesSquare, Settings, Table2 } from 'lucide-react'

export const NAV_GROUPS = [
  {
    label: null,
    items: [
      { to: '/app', label: 'Home', icon: Home, end: true },
      { to: '/app/analyze', label: 'Ask AI', icon: MessagesSquare },
      { to: '/app/datasets', label: 'Datasets', icon: Database },
      { to: '/app/spreadsheet', label: 'Spreadsheet', icon: Table2 },
      { to: '/app/reports', label: 'Reports', icon: FileText },
      { to: '/app/saved', label: 'Saved', icon: Bookmark },
    ],
  },
]

export const FOOTER_ITEMS = [
  { to: '/app/settings', label: 'Settings', icon: Settings, match: (p) => p.startsWith('/app/settings') && !p.endsWith('/billing') },
  { to: '/app/billing', label: 'Plan & billing', icon: CreditCard, match: (p) => p === '/app/billing' || p === '/app/settings/billing' },
]

export const TITLES = {
  '/app': 'Home',
  '/app/analyze': 'Ask AI',
  '/app/datasets': 'Datasets',
  '/app/spreadsheet': 'Spreadsheet',
  '/app/reports': 'Reports',
  '/app/saved': 'Saved',
  '/app/billing': 'Plan & billing',
}

export function pageTitle(pathname) {
  if (pathname.startsWith('/app/settings')) return 'Settings'
  return TITLES[pathname.replace(/\/$/, '')] || 'Workspace'
}
