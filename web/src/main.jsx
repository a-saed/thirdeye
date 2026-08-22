import React from 'react'
import { createRoot } from 'react-dom/client'
import Home from './routes/home.tsx'
import ReportCard from './routes/report.tsx'
import TokensPage from './routes/tokens.tsx'
import Compare from './routes/compare.tsx'
import NotFound from './routes/notfound.tsx'
import './style.css'

// Deliberately not a router. Four screens, no nested routes, no transitions
// worth a dependency. Both /report and #/report work, so the pages survive
// being opened from a static build with no history fallback.
const path = window.location.pathname.replace(/\/+$/, '')
const hash = window.location.hash.replace(/^#\/?/, '')
const route = (hash || path.replace(/^\//, '')).split('?')[0]

const PAGES = {
  '': { Component: Home, cls: 'route-home' },
  report: { Component: ReportCard, cls: 'route-report' },
  tokens: { Component: TokensPage, cls: 'route-tokens' },
  compare: { Component: Compare, cls: 'route-compare' },
}

// An unknown path gets a REAL 404, not the home map. The SPA fallback serves
// index.html for everything, so without this an address that does not exist
// silently rendered a different page — the one habit this product cannot have.
const page = PAGES[route] ?? { Component: NotFound, cls: 'route-notfound' }
document.body.classList.add(page.cls)

createRoot(document.getElementById('root')).render(<page.Component />)
