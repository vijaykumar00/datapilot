# Sitemap Generation

`frontend/public/sitemap.xml` and the sitemap reference in `frontend/public/robots.txt` are generated from `src/data/marketing.js` by `scripts/generate-sitemap.mjs`.

The build pipeline runs `npm run generate:sitemap` before `npm run build`, so public marketing and legal routes come from one route configuration source.

Environment behavior:

- Local: omit `VITE_PUBLIC_SITE_URL`; the script uses `http://localhost:5173`.
- Staging: set `VITE_PUBLIC_SITE_URL` to the staging origin before building.
- Production: set `VITE_PUBLIC_SITE_URL` to the confirmed production origin before building.

The generator writes absolute sitemap URLs, writes an absolute `robots.txt` sitemap reference, and excludes private/auth routes such as `/app/*`, `/login`, and `/signup`.
