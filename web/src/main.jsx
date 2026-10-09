import React from 'react'
import { createRoot } from 'react-dom/client'
import Home from './routes/home.tsx'
import ReportCard from './routes/report.tsx'
import TokensPage from './routes/tokens.tsx'
import Compare from './routes/compare.tsx'
import Search from './routes/search.tsx'
import NotFound from './routes/notfound.tsx'
import maplibregl from 'maplibre-gl'
import rtlTextPlugin from '@mapbox/mapbox-gl-rtl-text/mapbox-gl-rtl-text.min.js?url'
import './style.css'

// MapLibre does not shape right-to-left scripts on its own: without this
// plugin every Arabic label renders with its letters reversed and unjoined,
// on any basemap. Registered once here, before any page builds a map (a
// second registration throws). Lazy: fetched only when a tile has RTL text.
// Self-hosted via ?url so a third-party CDN outage cannot garble the map.
// Pinned to 0.2.x: 0.3 is built for Mapbox GL v3 and fails to load in
// MapLibre's workers ("RTL Text Plugin failed to import scripts").
maplibregl.setRTLTextPlugin(rtlTextPlugin, true).catch(() => {})

// Deliberately not a router. Five screens, no nested routes, no transitions
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
  search: { Component: Search, cls: 'route-search' },
}

// An unknown path gets a REAL 404, not the home map. The SPA fallback serves
// index.html for everything, so without this an address that does not exist
// silently rendered a different page — the one habit this product cannot have.
const page = PAGES[route] ?? { Component: NotFound, cls: 'route-notfound' }
document.body.classList.add(page.cls)

createRoot(document.getElementById('root')).render(<page.Component />)
