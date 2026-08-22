/*
 * HOME — the coverage map, and the way into a report.
 *
 * Spec: docs/DESIGN.md. Tokens: src/tokens.css.
 *
 * The map comes FIRST, before any location is chosen, deliberately: the user
 * should be picking a spot while already looking at where the evidence is
 * thick and where it is thin. A search box that let someone type an address
 * and receive a confident-looking report would hide the single most important
 * fact about this dataset — that 22% of inhabited cells have no business data
 * at all and 66% rest on one source.
 *
 * Coverage membership is tested against the h3 index, not against rendered
 * pixels: latLngToCell at res-8 and a Set lookup. queryRenderedFeatures would
 * depend on zoom, tile loading and layer filters, so a click near the edge
 * could report "not covered" purely because the cell had not drawn yet.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { latLngToCell } from 'h3-js'
import 'maplibre-gl/dist/maplibre-gl.css'
import MapControls, { type Located } from '../components/MapControls'
import { useDelayed } from '../components/async'
import {
  coverageFillColor, coverageFillOpacity, coverageLinePaint,
} from '../map/paint.mjs'
import '../components/MapControls.css'
import '../tokens.css'
import './home.css'

const DARK_MATTER = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const VEIL_ALPHA = 0.45
const COVERAGE_RES = 8

type Conf = 'corroborated' | 'single_source' | 'unavailable'

const CONF_LABEL: Record<Conf, string> = {
  corroborated: 'Corroborated',
  single_source: 'Single source',
  unavailable: 'No business data',
}
const CONF_GLYPH: Record<Conf, string> = {
  corroborated: '●', single_source: '○', unavailable: '–',
}

interface Summary {
  all_cells: { cells: number; pct: Record<Conf, number> }
  inhabited: { cells: number; pct: Record<Conf, number> }
  inhabited_by_governorate: Record<string, { cells: number; pct: Record<Conf, number> }>
}

interface Picked {
  lat: number; lon: number
  covered: boolean
  conf?: Conf; gov?: string; n?: number; inhabited?: boolean
  /** Set only when the point came from the browser's locator. */
  accuracyM?: number
}

/* A 500 m catchment around a point known to +-3 km is not a report, it is a
   guess with a decimal point. Above this the location is shown but the report
   is withheld. */
const ACCURACY_LIMIT_M = 500

/** Metres below a kilometre, kilometres above it. A "±3400 m" reads as
 *  precision; "±3.4 km" reads as the guess it is. */
function fmtAccuracy(m: number): string {
  return m >= 1000 ? `±${(m / 1000).toFixed(1)} km` : `±${Math.round(m)} m`
}

type Hit = {
  name: string; detail: string; lat: number; lon: number
  kind?: string; source?: string
}
type HitWithCoverage = Hit & {
  covered: boolean; cellCount?: number; gov?: string
}

/** SEARCH, AS A FLOATING PILL OVER THE MAP.
 *
 *  Worldwide, deliberately. Third Eye is a method that runs wherever open data
 *  exists; restricting the geocoder to one country would bake today's coverage
 *  into the product. Searching a place we cannot report on is a legitimate
 *  question with an honest answer — "not covered yet" — and refusing to look
 *  is worse than answering.
 *
 *  Every result carries its coverage status BEFORE you click, resolved locally
 *  against the res-8 cell index already in memory. Learning that a place is
 *  uncovered after navigating there is the frustrating version.
 */
function SearchBox({ onPick, lookup, regions }: {
  onPick: (lat: number, lon: number, covered: boolean) => void
  lookup: (lat: number, lon: number) => { covered: boolean; n?: number; gov?: string }
  regions: string[]
}) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<HitWithCoverage[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [degraded, setDegraded] = useState<string | null>(null)
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  // Selecting a result writes its name into the field, which re-triggers the
  // search effect and reopens the list 400ms later — the panel appeared to
  // pop back up on its own. One-shot skip: the next run of the effect is the
  // echo of a selection, not a query.
  const skipSearch = useRef(false)

  // "/" and cmd-K focus the field, the way every tool with a search does now.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = ['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement)?.tagName)
      if ((e.key === '/' && !typing) || (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey))) {
        e.preventDefault(); inputRef.current?.focus(); inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [])

  useEffect(() => {
    if (skipSearch.current) { skipSearch.current = false; setBusy(false); return }
    const term = q.trim()
    if (term.length < 3) { setResults([]); setOpen(false); return }
    let cancelled = false
    setBusy(true)
    // Debounced: Nominatim's policy is 1 req/s, and a request per keystroke
    // would breach it on its own.
    const t = setTimeout(() => {
      fetch(`/api/geocode/search?q=${encodeURIComponent(term)}`)
        .then(r => (r.ok ? r.json() : { results: [] }))
        .then(d => {
          if (cancelled) return
          const withCov: HitWithCoverage[] = (d.results ?? []).map((r: Hit) => {
            const c = lookup(r.lat, r.lon)
            return { ...r, covered: c.covered, cellCount: c.n, gov: c.gov }
          })
          setResults(withCov)
          setDegraded(d.place_search_unavailable ?? null)
          setCursor(0); setOpen(true); setBusy(false)
        })
        .catch(() => { if (!cancelled) { setResults([]); setBusy(false) } })
    }, 400)
    return () => { cancelled = true; clearTimeout(t) }
  }, [q, lookup])

  const ordered = useMemo(() => [
    ...results.filter(r => r.kind === 'business'),
    ...results.filter(r => r.kind !== 'business'),
  ], [results])

  const choose = (r: HitWithCoverage) => {
    skipSearch.current = true
    setOpen(false)
    setQ(r.name)
    inputRef.current?.blur()   // otherwise onFocus can immediately reopen it
    onPick(r.lat, r.lon, r.covered)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur(); return }
    if (!open || !ordered.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => (c + 1) % ordered.length) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => (c - 1 + ordered.length) % ordered.length) }
    if (e.key === 'Enter') { e.preventDefault(); choose(ordered[cursor]) }
  }

  const groups: [string, HitWithCoverage[]][] = [
    ['In our records', ordered.filter(r => r.kind === 'business')],
    ['Places', ordered.filter(r => r.kind !== 'business')],
  ]

  return (
    <div className="hm-search" ref={boxRef}>
      <div className="hm-search-pill">
        <svg className="hm-search-icon" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 L14 14" />
        </svg>
        <input
          ref={inputRef}
          className="hm-search-input"
          value={q}
          placeholder="Search anywhere"
          onChange={e => setQ(e.target.value)}
          onFocus={() => { if (results.length && q.trim().length >= 3 && !skipSearch.current) setOpen(true) }}
          onKeyDown={onKeyDown}
          aria-label="Search for a place or business"
        />
        {busy
          ? <span className="hm-search-busy">…</span>
          : q
            ? <button className="hm-search-clear" onClick={() => { setQ(''); setResults([]) }}>×</button>
            : <kbd className="hm-search-kbd">/</kbd>}
      </div>

      {open && (
        <div className="hm-search-card">
          {degraded && (
            <p className="hm-search-none">
              Place lookup unavailable — showing matches from our own records only.
            </p>
          )}
          {!ordered.length && !busy && (
            <p className="hm-search-none">No match for “{q.trim()}”.</p>
          )}
          {groups.map(([title, rows]) => rows.length ? (
            <div className="hm-search-group" key={title}>
              <div className="hm-search-group-h">{title}</div>
              <ul>
                {rows.map(r => {
                  const i = ordered.indexOf(r)
                  return (
                    <li key={`${r.lat}-${r.lon}-${r.name}`}>
                      <button
                        className={i === cursor ? 'on' : undefined}
                        onMouseEnter={() => setCursor(i)}
                        onClick={() => choose(r)}
                      >
                        <span className="hm-search-name">{r.name}</span>
                        <span className="hm-search-detail">
                          {r.detail}
                          {r.source && <span className="hm-search-src"> · {r.source}</span>}
                        </span>
                        {/* Coverage BEFORE the click, not after. */}
                        <span className={'hm-cov ' + (r.covered ? 'hm-cov-in' : 'hm-cov-out')}>
                          {r.covered
                            ? `In coverage · ${(r.cellCount ?? 0).toLocaleString()} businesses in this cell`
                            : 'Not covered yet — no data for this region'}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null)}
          <div className="hm-search-foot">
            <span>↑↓ navigate · ↵ select · esc close</span>
            <span className="hm-dim">Live: {regions.join(', ')}</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Home() {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markerRef = useRef<maplibregl.Marker | null>(null)
  const cellsRef = useRef<Map<string, any>>(new Map())

  const [summary, setSummary] = useState<Summary | null>(null)
  const [regions, setRegions] = useState<{ name: string; cells?: number }[]>([])
  const [regionsOpen, setRegionsOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [note, setNote] = useState('')
  const [picked, setPicked] = useState<Picked | null>(null)
  const [inhabitedOnly, setInhabitedOnly] = useState(false)
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // The coverage layer is the screen's entire content. Until it lands the map
  // is a basemap with nothing on it, which reads as "no coverage anywhere"
  // rather than "still loading" — the exact confusion this product cannot
  // afford. State it, and offer a retry.
  const [layerState, setLayerState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [reloadNonce, setReloadNonce] = useState(0)
  // Re-render once the map exists so the controls get a live instance.
  const [, setMapReady] = useState(0)

  /* One selection path for both inputs: a click and a geolocate fix must be
     judged by exactly the same coverage test, or the two could disagree at a
     cell boundary. Uses only refs and setState, so it is stable. */
  const selectPoint = useCallback((lat: number, lon: number, accuracyM?: number) => {
    const map = mapRef.current
    if (!map) return
    const p = cellsRef.current.get(latLngToCell(lat, lon, COVERAGE_RES))
    setPicked(p
      ? { lat, lon, covered: true, conf: p.conf, gov: p.gov, n: p.n, inhabited: p.inh === 1, accuracyM }
      : { lat, lon, covered: false, accuracyM })

    const el = document.createElement('div')
    el.className = 'hm-pin' + (p ? '' : ' hm-pin-out')
    if (markerRef.current) markerRef.current.remove()
    markerRef.current = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map)
  }, [])

  const onLocate = useCallback((l: Located) => {
    const map = mapRef.current
    if (!map) return
    map.flyTo({ center: [l.lon, l.lat], zoom: Math.max(map.getZoom(), 12.5) })
    selectPoint(l.lat, l.lon, l.accuracyM)
  }, [selectPoint])

  useEffect(() => {
    fetch('/coverage-summary.json').then(r => r.json()).then(setSummary).catch(() => {})
    // Live regions come from pipeline/config/regions.json via the export, so a
    // new city is a config change and no sentence here names a place.
    fetch('/regions.json').then(r => r.json())
      .then(d => { setRegions(d.regions ?? []); setNote(d.roadmap_note ?? '') })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!ref.current) return
    const cs = getComputedStyle(document.documentElement)
    const t = (k: string) => cs.getPropertyValue(k).trim()
    const map = new maplibregl.Map({
      container: ref.current,
      style: DARK_MATTER,
      center: [31.05, 30.15],
      zoom: 7.4,
      attributionControl: false,
    })
    mapRef.current = map
    setMapReady(v => v + 1)
    map.on('error', e => setErr((e as any)?.error?.message || 'basemap unavailable'))

    map.on('load', async () => {
      try {
        // One --canvas layer above every imported basemap layer: desaturates
        // the basemap and dims its labels in a single move.
        map.addLayer({
          id: 'veil', type: 'background',
          paint: { 'background-color': t('--canvas'), 'background-opacity': VEIL_ALPHA },
        })

        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 20000)
        const res = await fetch('/coverage-res8.geojson', { signal: ctrl.signal })
        clearTimeout(timer)
        if (!res.ok) throw new Error(`coverage layer: HTTP ${res.status}`)
        const fc = await res.json()
        for (const f of fc.features) cellsRef.current.set(f.properties.h3, f.properties)

        map.addSource('cells', { type: 'geojson', data: fc })
        // Paint lives in src/map/paint.mjs, validated by npm run validate:style
        // on every build — see that file for why.
        const tk = {
          accent: t('--accent'), amber: t('--amber'), noData: t('--map-no-data'),
          alphaCorroborated: parseFloat(t('--alpha-corroborated')),
          alphaSingle: parseFloat(t('--alpha-single')),
          alphaNoData: parseFloat(t('--alpha-nodata')),
        }
        map.addLayer({
          id: 'cells-fill', type: 'fill', source: 'cells',
          paint: {
            'fill-color': coverageFillColor(tk) as any,
            'fill-opacity': coverageFillOpacity(tk) as any,
          },
        })
        map.addLayer({
          id: 'cells-line', type: 'line', source: 'cells',
          paint: coverageLinePaint() as any,
        })
        map.getCanvas().style.cursor = 'crosshair'
        setReady(true)
        setLayerState('ok')
      } catch (e: any) {
        setErr(e?.name === 'AbortError'
          ? 'The coverage layer timed out after 20s.'
          : `The coverage layer failed to load: ${e.message}.`)
        setLayerState('error')
      }
    })

    map.on('click', e => selectPoint(e.lngLat.lat, e.lngLat.lng))

    return () => { map.remove(); mapRef.current = null }
  }, [selectPoint, reloadNonce])

  useEffect(() => {
    const map = mapRef.current
    // getLayer guard: if the fill layer failed to add, setFilter raises a map
    // error that masks the real cause with "cannot filter non-existing layer".
    if (!map || !ready || !map.getLayer('cells-fill')) return
    const f = inhabitedOnly ? ['==', ['get', 'inh'], 1] : null
    map.setFilter('cells-fill', f as any)
    if (map.getLayer('cells-line')) map.setFilter('cells-line', f as any)
  }, [inhabitedOnly, ready])

  const tooVague = picked?.accuracyM != null && picked.accuracyM > ACCURACY_LIMIT_M

  const openReport = () => {
    if (!picked?.covered || tooVague) return
    window.location.href = `/report?lat=${picked.lat.toFixed(5)}&lon=${picked.lon.toFixed(5)}`
  }

  const showLayerSkel = useDelayed(layerState === 'loading')

  const govRows = useMemo(
    () => Object.entries(summary?.inhabited_by_governorate ?? {})
      .sort((a, b) => a[1].pct.unavailable - b[1].pct.unavailable),
    [summary],
  )

  return (
    <div className="hm">
      <div className="hm-map" ref={ref} />
      {/* Sibling of the map container, not a child: MapLibre appends its own
          nodes into that element and React reconciliation should not share it. */}
      <MapControls map={mapRef.current} onLocate={onLocate} />

      {/* TOP BAR: identity, search and coverage status as one object.
          Loose over the map they were three floating things competing with the
          data; together they read as chrome and leave the map alone. The left
          panel is then purely about coverage, which is what it is for. */}
      <div className="hm-topbar">
        <a className="hm-brand" href="/">
          <img src="/brand/lockup-compact-teal.svg" height={32} alt="Third Eye" />
        </a>
        <SearchBox
          regions={regions.map(r => r.name)}
          lookup={(lat, lon) => {
            const p = cellsRef.current.get(latLngToCell(lat, lon, COVERAGE_RES))
            return { covered: !!p, n: p?.n, gov: p?.gov }
          }}
          onPick={(lat, lon) => {
            const map = mapRef.current
            if (!map) return
            // An out-of-coverage pick still flies there. The panel then says
            // what we do not have, which is a real answer.
            map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 13) })
            selectPoint(lat, lon)
          }}
        />
        {regions.length > 0 && (
          <div className="hm-regions">
            {/* No status dot: a green light reads as "system operational", not
                as "these are the places we hold data for". */}
            <button
              className={'hm-live-chip' + (regionsOpen ? ' on' : '')}
              onClick={() => setRegionsOpen(o => !o)}
              aria-expanded={regionsOpen}
            >
              {regions.length} region{regions.length === 1 ? '' : 's'} live
              <span className="hm-chip-caret">{regionsOpen ? '▴' : '▾'}</span>
            </button>
            {regionsOpen && (
              <div className="hm-regions-card">
                <div className="hm-regions-h">Live now</div>
                <ul>
                  {regions.map(r => (
                    <li key={r.name}>
                      <span>{r.name}</span>
                      <span className="num hm-dim">
                        {(r.cells ?? 0).toLocaleString()} cells
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="hm-regions-note">{note}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {err && (
        <div className="hm-err">
          <strong>Map layer failed.</strong> {err} The map still works — you can
          search or click, you just cannot see where the data is.
          <button className="as-retry" onClick={() => { setErr(null); setLayerState('loading'); setReloadNonce(n => n + 1) }}>
            Try again
          </button>
        </div>
      )}
      {layerState === 'loading' && showLayerSkel && (
        <div className="hm-loading">Loading coverage…</div>
      )}

      <div className="hm-panel">
        {/* THE PANEL ORIENTS, IT DOES NOT SELL — see docs/DESIGN.md §10.
            Category first, one concrete claim, and the differentiator tied to
            something visible: the grey cells in the legend directly below are
            the "record runs out" this names, so the claim is demonstrated
            rather than argued. No city appears here; coverage is the chip. */}
        <h1 className="hm-h1">Location intelligence from open data</h1>
        <p className="hm-lede">
          Businesses, population and construction trend for any point on the
          map. Every figure names its sources and its date — where the record
          runs out, the map stays grey.
        </p>
        <p className="hm-cta">Click anywhere, or search above.</p>
        <a className="hm-secondary" href="/compare">
          Compare two locations →
        </a>

        {summary && (
          <>
            {/* ONE legend. Opening "Coverage detail" reveals the percentage
                columns on these same rows rather than printing a second copy
                of the class names underneath — which is what it was doing. */}
            <div className="hm-legend">
              {detailOpen && (
                <div className="hm-legend-head">
                  <span className="hm-lab" />
                  <span className="hm-pct">all</span>
                  <span className="hm-pct">inhabited</span>
                </div>
              )}
              {(['corroborated', 'single_source', 'unavailable'] as Conf[]).map(k => (
                <div className="hm-legend-row" key={k}>
                  <span className={`hm-sw hm-sw-${k}`} />
                  <span className="hm-lab">{CONF_LABEL[k]}</span>
                  {detailOpen && (
                    <>
                      <span className="hm-pct num hm-dim">
                        {summary.all_cells.pct[k].toFixed(1)}%
                      </span>
                      <span className="hm-pct num">
                        {summary.inhabited.pct[k].toFixed(1)}%
                      </span>
                    </>
                  )}
                </div>
              ))}
            </div>

            <label className="hm-toggle">
              <input
                type="checkbox" checked={inhabitedOnly}
                onChange={e => setInhabitedOnly(e.target.checked)}
              />
              Hide uninhabited cells
            </label>

            <button
              className="hm-detail-toggle"
              onClick={() => setDetailOpen(o => !o)}
              aria-expanded={detailOpen}
            >
              <span className="hm-detail-caret">{detailOpen ? '▾' : '▸'}</span>
              Coverage detail
            </button>

            {detailOpen && (
              <div className="hm-detail-body">
                <p className="hm-hint">
                  “No business data” is not “no businesses” — it means no source covers
                  that cell.
                </p>
                {govRows.length > 0 && (
                  <div className="hm-gov">
                    <div className="hm-gov-h">No business data, inhabited cells</div>
                    {govRows.map(([g, st]) => (
                      <div className="hm-gov-row" key={g}>
                        <span className="hm-lab">{g}</span>
                        <span className="num hm-dim">{st.cells.toLocaleString()}</span>
                        <span className="num">{st.pct.unavailable.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                )}
                {/* Attribution and sources belong on the page, not only in the
                    map's ⓘ: they are licence conditions, and on this product
                    they are also the argument. */}
                <p className="hm-sources">
                  Sources: Overture, Foursquare OS Places, Kontur, GHSL, Google
                  Open Buildings, OpenStreetMap.{' '}
                  <a href="/tokens">Design system</a>
                  <span className="hm-dot">·</span>
                  <a href="https://github.com/a-saed/thirdeye/issues" target="_blank" rel="noreferrer noopener">
                    Report an issue
                  </a>
                </p>
              </div>
            )}
          </>
        )}

        {picked && picked.covered && (
          <div className="hm-pick">
            <div className="hm-pick-head">
              <span className="num">{picked.lat.toFixed(5)}, {picked.lon.toFixed(5)}</span>
              <span className={`hm-badge hm-badge-${picked.conf}`}>
                <span className="hm-glyph">{CONF_GLYPH[picked.conf as Conf]}</span>
                {CONF_LABEL[picked.conf as Conf]}
              </span>
            </div>
            <div className="hm-pick-sub">
              {picked.gov}
              <span className="hm-dot">·</span>
              <span className="num">{picked.n?.toLocaleString()}</span> businesses in this cell
              {!picked.inhabited && (
                <>
                  <span className="hm-dot">·</span>
                  <span className="hm-warn">uninhabited cell</span>
                </>
              )}
            </div>
            {picked.accuracyM != null && (
              <div className={'hm-acc' + (tooVague ? ' hm-warn' : '')}>
                {/* The browser's number is about YOUR DEVICE. It is not this
                    product's precision, and printing "±1 m" next to a report
                    built from records that disagree by 10.2 m median and 58.5 m
                    at p90 implied a resolution nothing here has. Both figures,
                    each attributed. */}
                Your browser places you to {fmtAccuracy(picked.accuracyM)}.
                {tooVague ? (
                  <> That is wider than the {ACCURACY_LIMIT_M} m catchment — drop a pin
                     manually for a real report.</>
                ) : (
                  <span className="hm-dim">
                    {' '}Our records are block-level regardless: sources disagree by 10.2 m
                    median, 58.5 m at p90.
                  </span>
                )}
              </div>
            )}
            <div className="hm-actions">
              <button className="hm-btn" onClick={openReport} disabled={tooVague}>
                {tooVague ? 'Too imprecise for a report' : 'Open report'}
              </button>
              {/* Compare is a front-door action, not something buried inside a
                  report: people arrive already choosing between locations. */}
              <button
                className="hm-btn hm-btn-alt"
                onClick={() => {
                  if (!picked?.covered || tooVague) return
                  window.location.href =
                    `/compare?a=${picked.lat.toFixed(5)},${picked.lon.toFixed(5)}`
                }}
                disabled={tooVague}
              >
                Compare with…
              </button>
            </div>
            {tooVague && (
              <p className="hm-out-sub">
                Your browser could not place you closely enough to centre a{' '}
                {ACCURACY_LIMIT_M} m catchment. Click the exact spot on the map instead.
              </p>
            )}
          </div>
        )}

        {picked && !picked.covered && (
          <div className="hm-pick hm-pick-out">
            <div className="hm-pick-head">
              <span className="num">{picked.lat.toFixed(5)}, {picked.lon.toFixed(5)}</span>
            </div>
            <p className="hm-out">
              <strong>We don't cover this location yet.</strong> It falls outside the
              regions we have processed, so there is no report for this point — not a
              thin one, none.
            </p>
            <p className="hm-out-sub">
              {regions.length > 0 && <>Live now: {regions.map(r => r.name).join(' and ')}. </>}
              {note} Extending coverage means a pipeline run over a new area, not a
              setting we can flip.
            </p>
          </div>
        )}

      </div>
    </div>
  )
}
