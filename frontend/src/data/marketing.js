export const siteConfig = {
  name: 'DataPilot',
  tagline: 'SaaS analytics platform',
  description: 'Conversational spreadsheet analytics for CSV and Excel workbooks.',
  defaultTitle: 'DataPilot - Conversational Spreadsheet Analytics',
  defaultDescription:
    'Upload CSV or Excel workbooks, ask questions in plain English, and turn tabular data into explainable answers, charts, and reports.',
  ogImage: '/assets/og-image.png',
}

export const publicSiteUrl =
  (import.meta.env?.VITE_PUBLIC_SITE_URL || 'http://localhost:5173').replace(/\/+$/, '')

export const marketingNavItems = [
  { label: 'Product', path: '/' },
  { label: 'Features', path: '/features' },
  { label: 'Use Cases', path: '/use-cases' },
  { label: 'Security', path: '/security' },
  { label: 'Pricing', path: '/pricing' },
  { label: 'Docs', path: '/docs' },
  { label: 'About', path: '/about' },
  { label: 'Contact', path: '/contact' },
]

export const legalNavItems = [
  { label: 'Privacy Policy', path: '/legal/privacy' },
  { label: 'Terms of Service', path: '/legal/terms' },
  { label: 'Cookie Policy', path: '/legal/cookie-policy' },
  { label: 'Acceptable Use', path: '/legal/acceptable-use' },
]

export const publicRouteMetadata = {
  '/': {
    title: 'DataPilot - Conversational Spreadsheet Analytics',
    description:
      'DataPilot helps teams analyze CSV and Excel data through conversational queries, explainable SQL, charts, and report-ready summaries.',
    eyebrow: 'Brand foundation',
    heading: 'DataPilot',
    summary:
      'A focused analytics workspace for turning spreadsheet files into trustworthy answers, charts, and narrative reports.',
    ctaLabel: 'Try free',
    ctaTo: '/signup',
    secondaryCtaLabel: 'Explore features',
    secondaryCtaTo: '/features',
  },
  '/features': {
    title: 'Features',
    description:
      'Explore DataPilot foundations for conversational querying, data profiling, chart creation, report generation, and saved analysis workflows.',
    eyebrow: 'Product capabilities',
    heading: 'Features built for spreadsheet analytics',
    summary:
      'This page will detail the core product capabilities. For Sprint 3.1 it establishes the route, metadata, and layout foundation.',
    ctaLabel: 'Try free',
    ctaTo: '/signup',
    secondaryCtaLabel: 'View documentation',
    secondaryCtaTo: '/docs',
  },
  '/use-cases': {
    title: 'Use Cases',
    description:
      'See how DataPilot supports sales, finance, operations, inventory, and reporting workflows that start with CSV or Excel files.',
    eyebrow: 'Analyst workflows',
    heading: 'Use cases for spreadsheet-heavy teams',
    summary:
      'Role and industry-specific pages will expand here. The foundation is ready for future use-case content without changing routing.',
    ctaLabel: 'Start a workspace',
    ctaTo: '/signup',
    secondaryCtaLabel: 'Review features',
    secondaryCtaTo: '/features',
  },
  '/security': {
    title: 'Security',
    description:
      'Review DataPilot security foundations including workspace isolation, encrypted provider keys, session handling, and controlled guest access.',
    eyebrow: 'Trust foundation',
    heading: 'Security starts with isolated workspaces',
    summary:
      'Security disclosures will mature in later sprints. This route now provides the public structure and metadata for review.',
    ctaLabel: 'Contact us',
    ctaTo: '/contact',
    secondaryCtaLabel: 'Read acceptable use',
    secondaryCtaTo: '/legal/acceptable-use',
  },
  '/pricing': {
    title: 'Pricing',
    description:
      'Compare DataPilot plans, usage limits, trial status, and secure upgrade paths backed by the subscription API.',
    eyebrow: 'Plan foundation',
    heading: 'Pricing',
    summary:
      'Public plan data is loaded from the backend catalog, with checkout and billing management routed through secure server-generated Stripe sessions.',
    ctaLabel: 'Try free',
    ctaTo: '/signup',
    secondaryCtaLabel: 'Talk to sales',
    secondaryCtaTo: '/contact',
  },
  '/about': {
    title: 'About',
    description:
      'Learn about DataPilot and its product direction: making spreadsheet analytics faster, clearer, and easier to verify.',
    eyebrow: 'Company',
    heading: 'About DataPilot',
    summary:
      'DataPilot is built around a simple idea: analysis should be conversational, explainable, and close to the source data.',
    ctaLabel: 'Contact the team',
    ctaTo: '/contact',
    secondaryCtaLabel: 'Open docs',
    secondaryCtaTo: '/docs',
  },
  '/contact': {
    title: 'Contact',
    description:
      'Contact DataPilot for product questions, sales discussions, support requests, or implementation planning.',
    eyebrow: 'Get in touch',
    heading: 'Contact DataPilot',
    summary:
      'Use this route as the future home for support and sales workflows. The current shell keeps the contact path stable.',
    ctaLabel: 'Sign in',
    ctaTo: '/login',
    secondaryCtaLabel: 'Try free',
    secondaryCtaTo: '/signup',
  },
  '/docs': {
    title: 'Documentation',
    description:
      'Open the DataPilot documentation foundation for uploads, querying, reports, provider setup, and workspace workflows.',
    eyebrow: 'Guides',
    heading: 'Documentation foundation',
    summary:
      'Documentation content will be expanded in a later sprint. The public route now has stable layout, metadata, and navigation.',
    ctaLabel: 'Try free',
    ctaTo: '/signup',
    secondaryCtaLabel: 'Contact support',
    secondaryCtaTo: '/contact',
  },
}

export const legalRouteMetadata = {
  '/legal/privacy': {
    title: 'Privacy Policy',
    description: 'Draft privacy policy foundation for DataPilot data handling, storage, cookies, and AI provider use.',
  },
  '/legal/terms': {
    title: 'Terms of Service',
    description: 'Draft terms of service foundation for DataPilot user responsibilities and service usage boundaries.',
  },
  '/legal/cookie-policy': {
    title: 'Cookie Policy',
    description: 'Draft cookie policy foundation for DataPilot functional session storage and browser preferences.',
  },
  '/legal/acceptable-use': {
    title: 'Acceptable Use Policy',
    description: 'Draft acceptable use policy foundation for DataPilot workspace and platform safety expectations.',
  },
}

export const publicSitemapRoutes = [
  ...Object.keys(publicRouteMetadata),
  ...Object.keys(legalRouteMetadata),
]
