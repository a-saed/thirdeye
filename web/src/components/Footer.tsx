import React from 'react'
import Disclosure from './Disclosure'
import './Footer.css'

/** Sources, licences and contact.
 *
 *  ATTRIBUTION IS A LICENCE CONDITION, NOT A CREDIT ROLL. OpenStreetMap and
 *  its derivatives are ODbL, Overture is ODbL/CDLA depending on theme, GHSL
 *  and Kontur carry their own terms. On a product whose entire argument is
 *  that it names what each number rests on, listing them is also the argument
 *  — the same discipline as the provenance on a metric card, applied to the
 *  product itself.
 */
const SOURCES = [
  { name: 'Overture Maps', what: 'business listings', licence: 'ODbL / CDLA',
    url: 'https://overturemaps.org' },
  { name: 'Foursquare OS Places', what: 'business listings', licence: 'Apache 2.0',
    url: 'https://location.foursquare.com/products/open-source-places/' },
  { name: 'Kontur', what: 'population', licence: 'CC BY 4.0',
    url: 'https://data.humdata.org/dataset/kontur-population-dataset' },
  { name: 'GHSL', what: 'built-up surface', licence: 'CC BY 4.0',
    url: 'https://human-settlement.emergency.copernicus.eu/' },
  { name: 'Google Open Buildings', what: 'building footprints', licence: 'CC BY 4.0',
    url: 'https://sites.research.google/open-buildings/' },
  { name: 'OpenStreetMap', what: 'place names, basemap', licence: 'ODbL',
    url: 'https://www.openstreetmap.org/copyright' },
  { name: 'CARTO', what: 'basemap style', licence: 'CARTO terms',
    url: 'https://carto.com/attributions' },
]

export default function Footer() {
  return (
    <footer className="ft">
      <div className="ft-row">
        <div className="ft-brand">
          <img src="/brand/lockup-compact-teal.svg" height={24} alt="Third Eye" />
          <p className="ft-tag">Location intelligence from open data.</p>
        </div>
        <div className="ft-links">
          {/* Repo rather than an email: honest for this stage, and no personal
              address goes on a public page. Swap for a real contact when a
              domain is registered. */}
          <a href="https://github.com/a-saed/thirdeye/issues" target="_blank" rel="noreferrer noopener">
            Report an issue
          </a>
          <a href="/tokens">Design system</a>
        </div>
      </div>

      {/* ATTRIBUTION IS A LICENCE CONDITION — see the note at the top of this
          file — so the fold is designed around that, not around tidiness.
          The collapsed summary NAMES THE LICENCES, which means the licence
          statement is present without interaction on every page; only the
          per-source links are behind the tap. This is what MapLibre's own
          attribution control does. On desktop there is no fold at all.
          Measured reason for folding: this footer cost 629px — 0.9 of a
          phone screen — on every route, and on /search it sat at 15,847px,
          which means nobody had ever reached it. */}
      <Disclosure summary="Data sources · ODbL, CDLA, CC BY" count={SOURCES.length}>
      <div className="ft-sources">
        {/* The desktop heading. Below 720px the Disclosure summary is the
            heading, and this is hidden so the words do not appear twice. */}
        <div className="ft-h">Data sources</div>
        <ul>
          {SOURCES.map(s => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer noopener">{s.name}</a>
              <span className="ft-what">{s.what}</span>
              <span className="ft-lic">{s.licence}</span>
            </li>
          ))}
        </ul>
      </div>
      </Disclosure>

      <p className="ft-note">
        Nothing here is a paid feed. Figures carry their own vintage and are only
        as current as the snapshot behind them; counts include unmerged
        duplicates, disclosed on every report rather than silently corrected.
      </p>
    </footer>
  )
}
