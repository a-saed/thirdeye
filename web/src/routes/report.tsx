/*
 * REPORT CARD — /report
 *
 * Spec: docs/DESIGN.md. Tokens: src/tokens.css.
 *
 * EVERYTHING COMES FROM GET /report. This file computes no metric, derives no
 * ratio and infers no confidence. Where it looked tempting — people per
 * competitor is one division — the computation was added to the API instead,
 * because a ratio inherits the provenance of its inputs (weakest-link
 * confidence, the OLDER of the two vintages) and a number produced here would
 * carry neither. The only thing derived client-side is map GEOMETRY: the h3
 * cells of the catchment, which the API does not return.
 *
 * The three rules that shape this screen:
 *   1. single_source is the DEFAULT state. 66% of inhabited cells are
 *      single-source. It gets a quiet amber badge and no warning styling —
 *      if it looked like an error the product would look broken everywhere.
 *   2. Missing is "—", never 0. Distinct concepts, and this is the easiest
 *      place in the whole product for the UI to lie.
 *   3. Vintage is visible without interaction. Population is a 2023 figure
 *      served in 2026.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { cellToBoundary } from 'h3-js'
import 'maplibre-gl/dist/maplibre-gl.css'
import MapControls from '../components/MapControls'
import { catchmentFillOpacity } from '../map/paint.mjs'
import { setMeta } from '../components/meta'
import Footer from '../components/Footer'
import CopyLink from '../components/CopyLink'
import { useFetch, useDelayed, Skel, ErrorBox, EmptyBox } from '../components/async'
import ConfBadge from '../components/ConfBadge'
import { fmt, cap, shortCategory } from '../lib/format'
import { CONF_LABEL, CONF_MEANING } from '../lib/confidence'
import { REPORT_RES, DEFAULT_K, MIN_PCT_BASE } from '../lib/thresholds'
import type {
  Conf, Metric, Report, PlaceRec, PlacesResp, Series, Point, CatchmentCell, PlaceLabel,
} from '../lib/types'
import '../components/MapControls.css'
import '../tokens.css'
import './report.css'

const DARK_MATTER = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const VEIL_ALPHA = 0.45

/* Road 9, Maadi — the study's ground-truth street, and the fallback when no
   point is supplied. Normally the location arrives from the home map. */
const DEFAULT = { lat: 29.9603, lon: 31.2580, radius: 500 }


function locationFromUrl() {
  const p = new URLSearchParams(window.location.search)
  const lat = parseFloat(p.get('lat') || '')
  const lon = parseFloat(p.get('lon') || '')
  const radius = parseInt(p.get('radius') || '', 10)
  return {
    lat: Number.isFinite(lat) ? lat : DEFAULT.lat,
    lon: Number.isFinite(lon) ? lon : DEFAULT.lon,
    radius: Number.isFinite(radius) && radius > 0 ? radius : DEFAULT.radius,
  }
}
const CATEGORIES = ['cafe', 'restaurant', 'pharmacy', 'grocery', 'gym'] as const










/* DISCRETE RINGS, NOT A SLIDER.
 * res-9 cells are ~0.105 km2, so a continuous radius control moves nothing for
 * 200 m and then jumps 7 cells to 19. Offering the steps the grid actually
 * supports is honest about what the data can resolve. Areas are approximate
 * because cell area varies with latitude; the exact figure for the catchment
 * chosen is shown in the panel. */
const RINGS = [
  { k: 0, cells: 1, label: '~0.1 km²', walk: '~2 min' },
  { k: 1, cells: 7, label: '~0.9 km²', walk: '~6 min' },
  { k: 2, cells: 19, label: '~2.3 km²', walk: '~10 min' },
] as const

export default function ReportCard() {
  // Read from the URL so a shared link restores the exact view, not just the
  // location. Validated against the known list — an unknown category in a
  // pasted link should fall back, not query for something that cannot exist.
  const [category, setCategory] = useState<string>(() => {
    const c = new URLSearchParams(window.location.search).get('category')
    return c && (CATEGORIES as readonly string[]).includes(c) ? c : 'cafe'
  })
  const [loc] = useState(locationFromUrl)
  const [label, setLabel] = useState<PlaceLabel | null>(null)
  const [cameFrom] = useState(compareOrigin)
  // Number(null) is 0, so a URL without ?k silently selected the single-cell
  // catchment. At that size a shop 30 m outside the boundary vanishes, and
  // cross-source position error is 58 m at p90 — two nearby pins could give
  // wildly different answers for reasons that are resolution, not geography.
  const [k, setK] = useState(() => {
    const raw = new URLSearchParams(window.location.search).get('k')
    if (raw === null) return DEFAULT_K
    const v = Number(raw)
    return Number.isInteger(v) && v >= 0 && v <= 2 ? v : DEFAULT_K
  })
  const [layers, setLayers] = useState<Layers>(loadLayers)
  const [hovered, setHovered] = useState<string | null>(null)
  // Hover is transient; focus is a decision. Clicking either half pins the
  // record so it stays highlighted while you look at the other one.
  const [focused, setFocused] = useState<string | null>(null)
  // Places are fetched ONCE here and shared by the map and the list, so a dot
  // and its row are guaranteed to be the same record.
  // Both payloads go through one hook: timeout, cancellation, retry, and a
  // failure that is stated rather than rendered as zeros.
  const reportUrl =
    `/api/report?lat=${loc.lat}&lon=${loc.lon}&k=${k}&category=${category}`
  const report = useFetch<Report>(reportUrl, 'The report')
  const data = report.state.s === 'ok' ? report.state.data : null
  const loading = report.state.s === 'loading'
  const err = report.state.s === 'error' ? report.state.message : null

  // Places are fetched ONCE here and shared by the map and the list, so a dot
  // and its row are guaranteed to be the same record. Its failure is
  // INDEPENDENT: the metrics still render if the list cannot load.
  const placesUrl =
    `/api/places?lat=${loc.lat}&lon=${loc.lon}&k=${k}&category=${category}&limit=1000`
  const placesReq = useFetch<PlacesResp>(placesUrl, 'The records list')
  const places = placesReq.state.s === 'ok' ? placesReq.state.data : null


  // A place name is a LABEL, never evidence. It comes from OSM via Nominatim,
  // which the study measured as contributing zero business records here — so
  // it names the spot and is not counted, compared or fed into any metric.
  // Failure is TOLERATED but no longer silent: the heading falls back to
  // coordinates and says the lookup is unavailable, rather than leaving a
  // permanent "Selected location" that looks like a bug.
  const geo = useFetch<PlaceLabel>(
    `/api/geocode/reverse?lat=${loc.lat}&lon=${loc.lon}`, 'Place name lookup')
  useEffect(() => {
    if (geo.state.s === 'ok' && geo.state.data?.name) setLabel(geo.state.data)
  }, [geo.state])

  // THE URL IS THE SHARE FORMAT. lat/lon arrived in it, but category and
  // catchment size lived only in React state — so a copied link reproduced the
  // place and then silently reset the query to defaults. replaceState rather
  // than pushState: changing a chip is refining a view, not navigating, and it
  // should not stack up back-button steps.
  useEffect(() => {
    const q = new URLSearchParams()
    q.set('lat', String(loc.lat))
    q.set('lon', String(loc.lon))
    q.set('k', String(k))
    q.set('category', category)
    window.history.replaceState(null, '', `/report?${q}`)
  }, [loc, k, category])

  useEffect(() => {
    const where = label?.name ?? `${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`
    const n = data?.metrics.find(m => m.metric === `business_count.${category}`)?.value
    const pop = data?.metrics.find(m => m.metric === 'population')?.value
    const headline = n != null
      ? `${fmt(n)} ${category}${n === 1 ? '' : 's'}${pop != null ? ` and ${fmt(pop)} people` : ''} within ${loc.radius} m.`
      : 'Businesses, population and construction for this point.'
    setMeta(
      `${where} — Third Eye`,
      `${headline} Every figure sourced and dated, with the gaps left visible.`,
    )
  }, [label, loc, data, category])

  // Remembered so the compare screen can offer somewhere already looked at
  // instead of making the user hunt the map twice.
  useEffect(() => {
    if (!label?.name) return
    try {
      const key = 'thirdeye.recent'
      const prev = JSON.parse(localStorage.getItem(key) || '[]')
      const entry = { lat: loc.lat, lon: loc.lon, name: label.name }
      const next = [entry, ...prev.filter((r: any) =>
        r.lat !== entry.lat || r.lon !== entry.lon)].slice(0, 8)
      localStorage.setItem(key, JSON.stringify(next))
    } catch { /* private mode */ }
  }, [label, loc])

  const byName = (n: string) => data?.metrics.find(m => m.metric === n)
  const competitors = byName(`business_count.${category}`)
  const population = byName('population')
  const perCompetitor = byName(`people_per_competitor.${category}`)
  // The fetch is in flight while `category` has already changed, so `data`
  // still describes the PREVIOUS category for a render or two. Reading a
  // series out of it then yields undefined and flashes a "no series" state
  // over a chart that is about to have data. Trust the response's own echo.
  const inSync = data?.query.category === category
  const series = inSync
    ? data!.time_series.find(s => s.metric === `business_count.${category}`)
    : undefined

  return (
    <div className="rc">
      <header className="rc-head rc-sticky">
        {/* Compact lockup: at header size the full lockup's 9px descriptor
            renders around 4.5px and is illegible. */}
        <a href="/" className="rc-home">
          <img src="/brand/lockup-compact-teal.svg" height={30} alt="Third Eye" />
        </a>
        <div className="rc-loc">
          <span className="rc-loc-name">
            {label?.name
              ?? (geo.state.s === 'loading' ? <Skel w={160} h={20} /> : 'Selected location')}
          </span>
          <span className="rc-loc-coord">
            {label?.detail && <>{label.detail}<span className="rc-dot">·</span></>}
            {geo.state.s === 'error' && (
              <>
                <span className="rc-dim" title={geo.state.message}>name unavailable</span>
                <span className="rc-dot">·</span>
              </>
            )}
            {/* Coordinates demoted to a subtitle: useful for checking, not a
                heading. Cell counts and the circle-vs-hexagon comparison are
                internal and have moved to the catchment panel. */}
            <span className="num">{loc.lat.toFixed(5)}, {loc.lon.toFixed(5)}</span>
            <span className="rc-dot">·</span>
            {loc.radius} m
          </span>
        </div>
      </header>
      <div className="rc-subnav">
        {/* Rebuilt from the two coordinate pairs, and carrying whatever the
            user has since changed here — switch to Pharmacy on the report and
            the comparison follows rather than snapping back. */}
        {cameFrom && (
          <a
            className="rc-back rc-back-primary"
            href={`/compare?${new URLSearchParams({
              ...(cameFrom.a ? { a: `${cameFrom.a.lat},${cameFrom.a.lon}` } : {}),
              ...(cameFrom.b ? { b: `${cameFrom.b.lat},${cameFrom.b.lon}` } : {}),
              k: String(k), category,
            })}`}
          >
            ← back to comparison
          </a>
        )}
        <a className="rc-back" href="/">← back to the coverage map</a>
        {!cameFrom && (
          <a className="rc-back" href={`/compare?a=${loc.lat},${loc.lon}&k=${k}&category=${category}`}>
            Compare with another location →
          </a>
        )}
        <CopyLink />
      </div>

      <div className="rc-controls">
        <div className="rc-chips">
        {CATEGORIES.map(c => (
          <button
            key={c}
            className={'rc-chip' + (c === category ? ' on' : '')}
            onClick={() => setCategory(c)}
          >
            {cap(c)}
          </button>
        ))}
        </div>
        <div className="rc-rings">
          <span className="rc-rings-label">Catchment</span>
          {RINGS.map(r => (
            <button
              key={r.k}
              className={'rc-ring' + (r.k === k ? ' on' : '')}
              onClick={() => setK(r.k)}
              title={`${r.cells} h3 cell${r.cells === 1 ? '' : 's'} at resolution ${REPORT_RES}`}
            >
              <span className="rc-ring-a">{r.label}</span>
              <span className="rc-ring-w">{r.walk} on foot</span>
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div className="rc-err">
          <strong>No report.</strong> {err}
          <div className="rc-err-sub">
            Nothing is rendered from a failed request — a zero here would be a
            fabricated number, not a missing one.
          </div>
          <button className="as-retry" onClick={report.retry}>Try again</button>
        </div>
      )}
      {loading && !err && <ReportSkeleton />}

      {data && !err && (
        <>
          <section className="rc-cards">
            <MetricCard
              label={`${cap(category)} competitors`} m={competitors}
              sub={competitors && (
                <>
                  {competitors.value_per_land_km2 != null ? (
                    <>{fmt(competitors.value_per_land_km2, 1)} per land km²</>
                  ) : (
                    <span className="rc-dim">
                      per-area figure withheld —{' '}
                      {competitors.value_per_land_km2_unavailable_reason}
                    </span>
                  )}
                  <span className="rc-dot">·</span>
                  includes {data.limitations.duplicate_inflation_pct_range[0]}–
                  {data.limitations.duplicate_inflation_pct_range[1]}% duplicate inflation,
                  unmerged
                </>
              )}
            />
            <MetricCard label="Population" m={population} />
            <MetricCard
              label={`People per ${category}`} m={perCompetitor}
              sub={perCompetitor && 'demand per outlet — higher is better'}
            />
            <div className="rc-card">
              <div className="rc-card-label">Saturation</div>
              <div className="rc-card-value">
                <span className="rc-sat">{data.context.saturation_class.toLowerCase()}</span>
              </div>
              <div className="rc-card-foot">
                <span className="num">{fmt(data.context.builtup_pct, 1)}%</span> built up
                {data.context.coverage_ratio != null && (
                  <>
                    <span className="rc-dot">·</span>
                    {/* "coverage ratio 1.05" means nothing to a reader. The
                        number stays in the tooltip for anyone who wants it. */}
                    <span title={`building footprint / built-up land = ${fmt(data.context.coverage_ratio, 2)}`}>
                      {data.context.coverage_ratio >= 1
                        ? 'built wall to wall'
                        : data.context.coverage_ratio >= 0.9
                          ? 'densely built'
                          : 'villa and garden fabric'}
                    </span>
                  </>
                )}
              </div>
              {/* Class-specific. The generic "built out" line was appearing under
                  DEVELOPING ground carrying measured growth — the one situation
                  in this dataset where the temporal signal actually fires,
                  described as though nothing were happening. */}
              {data.context.saturation_class === 'SATURATED' ? (
                <div
                  className="rc-card-foot"
                  title="A saturated catchment is already built out, so a flat construction signal means no new building — it says nothing about commercial change."
                >
                  built out — flat construction ≠ flat commerce
                </div>
              ) : data.context.builtup_growth_pct >= 5 ? (
                <div
                  className="rc-card-foot rc-growth"
                  title="GHSL built-up area, 2015 to 2025. The study found the construction signal only fires where there is room to build, which makes this one of the few places in the coverage area where it carries information."
                >
                  <span className="num">+{fmt(data.context.builtup_growth_pct, 0)}%</span>{' '}
                  built-up since 2015 — room to build, and it is being built
                </div>
              ) : (
                <div
                  className="rc-card-foot"
                  title="Room to build, but GHSL measured little new construction here between 2015 and 2025."
                >
                  room to build, little measured construction since 2015
                </div>
              )}
            </div>
          </section>

          <div className="rc-main">
            <section className="rc-panel">
              <CatchmentMap
                lat={data.query.lat} lon={data.query.lon}
                cells={data.context.cells ?? []}
                places={places?.places ?? []}
                layers={layers}
                hovered={hovered} focused={focused}
                onHover={setHovered} onFocus={setFocused}
              />
              <LayerBar
                layers={layers} onChange={setLayers}
                sources={sourceTally(places?.places ?? [])}
              />
              <dl className="rc-ctx">
                <div>
                  <dt>Area covered</dt>
                  <dd className="num">{fmt(data.context.land_area_km2, 2)} km²</dd>
                </div>
                <div>
                  <dt>Built up</dt>
                  <dd className="num">{fmt(data.context.builtup_pct, 0)}%</dd>
                </div>
              </dl>
              <p className="rc-ctx-note">
                {(1 - data.context.land_fraction_mean) > 0.02 ? (
                  <>
                    <strong>{Math.round((1 - data.context.land_fraction_mean) * 100)}%</strong>{' '}
                    of this area is water. Every per-area figure divides by the land only.
                  </>
                ) : (
                  <>Per-area figures divide by habitable land, never the raw circle.</>
                )}
              </p>
            </section>

            {/* The list sits BESIDE the map, not below it. Hover-linking a dot
                to its row only means anything if both are in one viewport —
                a highlight you have to scroll to find is not a link. The chart
                moves full width underneath, where it reads better anyway. */}
            <div className="rc-side">
              <PlaceList
                data={places} category={category}
                hovered={hovered} focused={focused}
                onHover={setHovered} onFocus={setFocused}
                status={placesReq.state.s === 'ok' ? 'ok' : placesReq.state.s}
                message={placesReq.state.s === 'error' ? placesReq.state.message : null}
                onRetry={placesReq.retry}
              />
            </div>
          </div>

          <Scrubber
            key={category}
            series={series}
            category={category}
            loading={!inSync || loading}
            total={competitors?.value}
            overtureCount={competitors?.source_counts?.overture}
          />

          <Verdict data={data} category={category} competitors={competitors} series={series} />
          <Footer />
        </>
      )}
    </div>
  )
}



/* ---------- metric card ---------- */




/* ---------- catchment map ---------- */




function LayerBar({ layers, onChange, sources }
: {
  layers: Layers; onChange: (l: Layers) => void
  sources: { overture: number; fsq: number; both: number; dup: number }
}) {
  const set = (patch: Partial<Layers>) => {
    const next = { ...layers, ...patch }
    saveLayers(next); onChange(next)
  }
  return (
    <div className="rc-layers">
      <div className="rc-layer-toggles">
        <label><input type="checkbox" checked={layers.points}
          onChange={e => set({ points: e.target.checked })} /> Business points</label>
        <label><input type="checkbox" checked={layers.hexes}
          onChange={e => set({ hexes: e.target.checked })} /> Coverage hexes</label>
        <label><input type="checkbox" checked={layers.bright}
          onChange={e => set({ bright: e.target.checked })} /> Bright basemap</label>
      </div>
      {layers.points && (
        <div className="rc-layer-legend">
          <span><i className="rc-dot-both" />both feeds {fmt(sources.both)}</span>
          <span><i className="rc-dot-ov" />overture {fmt(sources.overture)}</span>
          <span><i className="rc-dot-fsq" />foursquare {fmt(sources.fsq)}</span>
          {sources.dup > 0 && <span><i className="rc-dot-dup" />flagged {fmt(sources.dup)}</span>}
        </div>
      )}
    </div>
  )
}




function PlaceList({ data, category, hovered, focused, onHover, onFocus,
                     status, message, onRetry }: {
  data: PlacesResp | null; category: string
  hovered: string | null; focused: string | null
  onHover: (k: string | null) => void
  onFocus: (k: string | null) => void
  status: 'idle' | 'loading' | 'ok' | 'error'
  message?: string | null
  onRetry?: () => void
}) {
  const showSkel = useDelayed(status === 'loading')
  // Open by default: the list is the most convincing thing on the page and
  // collapsing it hid the argument. The toggle stays, because at 76 records it
  // does dominate the screen for someone heading to the chart — and the choice
  // is remembered for the session so it is not re-made on every pin drop.
  const [open, setOpen] = useState(() => {
    try { return sessionStorage.getItem('thirdeye.records') !== 'closed' } catch { return true }
  })
  useEffect(() => {
    try { sessionStorage.setItem('thirdeye.records', open ? 'open' : 'closed') } catch { /* private mode */ }
  }, [open])
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setFlaggedOnly(false) }, [category])

  const rows = useMemo(
    () => (data?.places ?? []).filter(p => !flaggedOnly || p.duplicate_suspected),
    [data, flaggedOnly],
  )

  // Hovering a dot scrolls its row into view; without this the link only works
  // in one direction and the map half feels dead.
  useEffect(() => {
    const key = hovered ?? focused
    if (!key || !bodyRef.current) return
    const el = bodyRef.current.querySelector(`[data-key="${CSS.escape(key)}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [hovered, focused])

  return (
    <section className="rc-places">
      <div className="rc-places-bar">
        <button className="rc-disclose" onClick={() => setOpen(o => !o)}>
          <span className="rc-disclose-arrow">{open ? '▾' : '▸'}</span>
          The {data ? fmt(data.total_unfiltered) + ' ' : ''}
          {category} record{data?.total_unfiltered === 1 ? '' : 's'} behind this count
        </button>
        {open && data && data.duplicate_flagged > 0 && (
          <label className="rc-place-filter">
            <input
              type="checkbox" checked={flaggedOnly}
              onChange={e => setFlaggedOnly(e.target.checked)}
            />
            Flagged only
          </label>
        )}
      </div>

      {open && (
        <div className="rc-places-body">
          {status === 'loading' && showSkel && <TableSkeleton />}
          {status === 'error' && (
            <ErrorBox message={message!} onRetry={onRetry} compact />
          )}
          {status === 'ok' && data && data.total_unfiltered === 0 && (
            <EmptyBox>
              No {category} records in this catchment. That is a measured zero,
              not a failed request — the sources cover this area and list none.
            </EmptyBox>
          )}
          {status === 'ok' && data && data.total_unfiltered > 0 && (
            <>
              <p className="rc-note rc-places-note">
                <span className="num">{fmt(data.total_unfiltered)}</span> records
                {data.duplicate_flagged > 0 && (
                  <>
                    , <span className="num rc-warn">{fmt(data.duplicate_flagged)}</span> flagged
                    as a suspected duplicate — nothing merged, both rows counted (matcher
                    precision was 25% out-of-sample, so a flag means look, not merge)
                  </>
                )}
                {(() => {
                  const stacked = (data.places ?? []).filter(p => p.same_point > 1).length
                  return stacked > 0 ? (
                    <>
                      . <span className="num">{fmt(stacked)}</span> sit on a shared
                      coordinate (×n) — distinct businesses the source placed at one
                      building centroid
                    </>
                  ) : null
                })()}
                .
              </p>

              <div className="rc-place-scroll" ref={bodyRef}>
                {/* On a phone the five columns become two: distance + name,
                    with source, category and flags folded under the name. A
                    five-column table at 390px is either horizontal scroll or
                    unreadable truncation, and neither is a table any more. */}
                <table className="rc-place-table">
                  <colgroup>
                    <col className="rc-col-dist" />
                    <col />
                    <col className="rc-col-flags" />
                    <col className="rc-col-src" />
                    <col className="rc-col-cat" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th className="num">dist</th>
                      <th>name</th>
                      <th className="rc-col-flags">flags</th>
                      <th className="rc-col-src">source</th>
                      <th className="rc-col-cat">category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((p, i) => {
                      const key = `${p.source}|${p.name}|${p.lat}|${p.lon}`
                      return (
                        <tr
                          key={`${key}-${i}`} data-key={key}
                          className={
                            (hovered === key ? 'rc-row-on ' : '') +
                            (focused === key ? 'rc-row-focus' : '') || undefined
                          }
                          onMouseEnter={() => onHover(key)}
                          onMouseLeave={() => onHover(null)}
                          onClick={() => onFocus(focused === key ? null : key)}
                        >
                          <td className="num rc-dim">{p.distance_m}</td>
                          <td className="rc-cell" title={p.name}>
                            {p.name || <span className="rc-dim">(unnamed)</span>}
                            {/* Only rendered on narrow screens, where the
                                dedicated columns are hidden. */}
                            <span className="rc-sub-meta">
                              {p.source} · {shortCategory(p.category)}
                              {p.duplicate_suspected && <span className="rc-tag rc-tag-dup">dup?</span>}
                              {p.same_point > 1 && <span className="rc-tag rc-tag-stack">×{p.same_point}</span>}
                            </span>
                          </td>
                          <td className="rc-flags">
                            {p.duplicate_suspected && (
                              <span className="rc-tag rc-tag-dup" title="Suspected duplicate — not merged. Both rows are kept and both are counted.">
                                dup?
                              </span>
                            )}
                            {p.same_point > 1 && (
                              <span
                                className="rc-tag rc-tag-stack"
                                title={`${p.same_point} records share this exact coordinate — the source placed them at one building or plaza centroid. Distinct businesses, one position.`}
                              >
                                ×{p.same_point}
                              </span>
                            )}
                          </td>
                          <td className="rc-dim">{p.source}</td>
                          <td className="rc-dim rc-cell" title={p.category}>
                            {shortCategory(p.category)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {data.total_unfiltered > data.returned && (
                <div className="rc-place-foot num">
                  showing the nearest <span className="num">{fmt(data.returned)}</span> of{' '}
                  <span className="num">{fmt(data.total_unfiltered)}</span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}



/* ---------- what we can and cannot say ---------- */


function MetricCard({ label, m, sub }
: {
  label: string; m?: Metric; sub?: React.ReactNode
}) {
  if (!m) {
    return (
      <div className="rc-card">
        <div className="rc-card-label">{label}</div>
        <div className="rc-card-value">
          <span className="num rc-missing">—</span>
          <ConfBadge c="unavailable" />
        </div>
        <div className="rc-card-foot">No source covers this metric in this catchment.</div>
      </div>
    )
  }
  const digits = m.metric.startsWith('people_per_competitor') ? 0 : 0
  return (
    <div className="rc-card">
      <div className="rc-card-label">{label}</div>
      <div className="rc-card-value">
        <span className="num">{fmt(m.value, digits)}</span>
        <ConfBadge c={m.confidence} />
      </div>
      {/* Vintage without interaction. Population is 2023, served now. */}
      <div className="rc-card-foot num">
        as of {m.as_of}
        {m.stale && <span className="rc-stale"> · stale: construction measured since</span>}
        <span className="rc-dot">·</span>
        <span className="rc-dim">{m.contributing_sources.join(', ')}</span>
      </div>
      <ConfidenceSplit m={m} />
      {/* A value measured at a coarser resolution was apportioned to this
          catchment, not observed at this scale. Same register as the vintage
          line, because it is the same kind of caveat. */}
      {m.native_res > 0 && m.native_res < REPORT_RES && (
        <div
          className="rc-card-foot"
          title={`Kontur publishes population on res-${m.native_res} hexagons. This catchment is res-${REPORT_RES}, so the value was apportioned across children by land area rather than observed at this scale.`}
        >
          estimated from res-{m.native_res} ({m.native_res === 8 ? '0.74 km²' : 'coarser'}) —
          not measured at this scale
        </div>
      )}
      {sub && <div className="rc-card-foot">{sub}</div>}
    </div>
  )
}



function ConfidenceSplit({ m }
: { m: Metric }) {
  const by = m.cells_by_confidence ?? {}
  const total = m.cells_total ?? 0
  if (!total) return null
  const corr = by.corroborated ?? 0
  const single = by.single_source ?? 0
  const parts: string[] = []
  if (corr) parts.push(`${corr} corroborated`)
  if (single) parts.push(`${single} single-source`)
  // "none present" is a measured zero; "no data" is a gap. Never the same word.
  if (m.cells_none_present) parts.push(`${m.cells_none_present} none present`)
  if (m.cells_no_data) parts.push(`${m.cells_no_data} no data`)
  if (!parts.length) parts.push('no data')

  return (
    <>
      <div className="rc-card-foot">
        {/* The denominator is ALWAYS the catchment's cell count. Cells with no
            row are named, not quietly dropped from the total. */}
        {/* Terse on purpose. Every fact that was here is still here; it just
            stopped being a paragraph. Six lines of caveat under a 23px number
            makes the caveat the loudest thing on the card, which inverts what
            the design is for. The weakest-link rule moved to the badge's
            tooltip — it explains the badge, so that is where it belongs. */}
        {parts.join(' · ')} of <span className="num">{total}</span> cells
      </div>
      {/* Only where two sources actually overlap. One source has nothing to
          agree with, and a ratio of 0 there reads as total disagreement. */}
      {m.agreement_ratio != null && m.contributing_sources.length > 1 && (
        <div className="rc-card-foot">
          sources differ <span className="num">{fmt(1 / m.agreement_ratio, 2)}×</span>{' '}
          where both cover
        </div>
      )}
    </>
  )
}



/** Layer state, kept for the session.
 *
 *  THREE TOGGLES, NEVER A LAYER MANAGER. A panel invites endless additions and
 *  most people never open one; if a fourth toggle ever feels necessary that is
 *  a signal the defaults are wrong, not that the panel needs a row.
 *
 *  Persisted so choices survive a pin drop — resetting the map every time
 *  someone picks a new location is the fastest way to make a control feel
 *  broken. */
export interface Layers { points: boolean; hexes: boolean; bright: boolean }
const LAYER_KEY = 'thirdeye.layers'
const DEFAULT_LAYERS: Layers = { points: true, hexes: true, bright: false }



/** Basemap veil. 0.45 makes the coverage ramp legible; 0.15 makes street names
 *  legible. Both are right for different jobs, which is why this is a toggle
 *  and not a compromise value that serves neither. */
const VEIL_DIM = 0.45
const VEIL_BRIGHT = 0.15

const pointKey = (p: PlaceRec) => `${p.source}|${p.name}|${p.lat}|${p.lon}`

function CatchmentMap({ lat, lon, cells, places, layers, hovered, focused, onHover, onFocus }
: {
  lat: number; lon: number
  cells: CatchmentCell[]
  places: PlaceRec[]
  layers: Layers
  hovered: string | null
  focused: string | null
  onHover: (k: string | null) => void
  onFocus: (k: string | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [, setMapReady] = useState(0)

  useEffect(() => {
    if (!ref.current) return
    const cs = getComputedStyle(document.documentElement)
    const map = new maplibregl.Map({
      container: ref.current, style: DARK_MATTER,
      center: [lon, lat], zoom: 14.2,
      attributionControl: false,
    })
    mapRef.current = map
    setMapReady(v => v + 1)
    map.on('error', e => setErr((e as any)?.error?.message || 'basemap unavailable'))

    map.on('load', () => {
      map.addLayer({
        id: 'veil', type: 'background',
        paint: {
          'background-color': cs.getPropertyValue('--canvas').trim(),
          'background-opacity': layers.bright ? VEIL_BRIGHT : VEIL_DIM,
        },
      })
      map.addSource('cells', { type: 'geojson', data: emptyFC() })
      map.addSource('pts', { type: 'geojson', data: emptyFC() })

      // Member cells, shaded by their OWN confidence: the split that reads as
      // "3 corroborated, 3 single-source, 1 no data" becomes a picture.
      map.addLayer({
        id: 'cell-fill', type: 'fill', source: 'cells',
        paint: {
          'fill-color': ['match', ['get', 'conf'],
            'corroborated', cs.getPropertyValue('--accent').trim(),
            'single_source', cs.getPropertyValue('--amber').trim(),
            cs.getPropertyValue('--map-no-data').trim()],
          'fill-opacity': ['match', ['get', 'conf'],
            'corroborated', 0.26, 'single_source', 0.16, 0.22],
        },
      })
      // THE OUTLINE IS NOT A LAYER. It is the report's subject, so it stays on
      // when the hex shading is switched off.
      map.addLayer({
        id: 'cell-outline', type: 'line', source: 'cells',
        paint: { 'line-color': 'rgba(255,255,255,0.28)', 'line-width': 1 },
      })
      map.addLayer({
        id: 'pt-halo', type: 'circle', source: 'pts',
        filter: ['==', ['get', 'key'], ''],
        paint: {
          'circle-radius': 9,
          'circle-color': cs.getPropertyValue('--text').trim(),
          'circle-opacity': 0.25,
        },
      })
      // A focused point keeps a ring after the cursor leaves.
      map.addLayer({
        id: 'pt-ring', type: 'circle', source: 'pts',
        filter: ['==', ['get', 'key'], ''],
        paint: {
          'circle-radius': 11, 'circle-color': 'transparent',
          'circle-stroke-width': 1.6,
          'circle-stroke-color': cs.getPropertyValue('--text').trim(),
        },
      })
      map.addLayer({
        id: 'pts', type: 'circle', source: 'pts',
        paint: {
          // Colour by SOURCE, not category: only one category is on screen at
          // a time, so a category icon would encode nothing. Which feed saw a
          // place is the thing that actually varies.
          'circle-color': ['match', ['get', 'src'],
            'both', cs.getPropertyValue('--accent').trim(),
            'overture', '#6BA8D8',
            '#C77FD0'],
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 3, 16, 6],
          // Duplicate-flagged points are hollowed rather than hidden: the
          // count includes them, so the map must too.
          'circle-opacity': ['case', ['==', ['get', 'dup'], 1], 0.25, 0.9],
          'circle-stroke-width': ['case', ['==', ['get', 'dup'], 1], 1.4, 0.6],
          'circle-stroke-color': ['case', ['==', ['get', 'dup'], 1],
            cs.getPropertyValue('--amber').trim(), 'rgba(0,0,0,0.55)'],
        },
      })

      map.on('mousemove', 'pts', e => {
        const f = e.features?.[0]
        if (f) { map.getCanvas().style.cursor = 'pointer'; onHover(f.properties!.key as string) }
      })
      map.on('mouseleave', 'pts', () => {
        map.getCanvas().style.cursor = ''
        onHover(null)
      })
      map.on('click', 'pts', e => {
        const f = e.features?.[0]
        if (f) onFocus(f.properties!.key as string)
      })
      // Clicking empty map clears the pin, so focus is escapable.
      map.on('click', e => {
        const hit = map.queryRenderedFeatures(e.point, { layers: ['pts'] })
        if (!hit.length) onFocus(null)
      })
      new maplibregl.Marker({ color: cs.getPropertyValue('--accent').trim(), scale: 0.7 })
        .setLngLat([lon, lat]).addTo(map)
      setReady(true)
    })
    // MapLibre sizes its canvas when the container is measured. A CSS-driven
    // resize (column collapse, sticky reflow) does not trigger that on its own,
    // so the canvas keeps a stale size and the tiles sit in the wrong box.
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(ref.current)

    return () => { ro.disconnect(); map.remove(); mapRef.current = null }
  }, [])

  // Recentre when the pin moves without tearing the map down.
  useEffect(() => {
    const map = mapRef.current
    if (map && ready) map.easeTo({ center: [lon, lat], duration: 300 })
  }, [lat, lon, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    const feats = cells.map(c => {
      const ring = cellToBoundary(c.h3, true)
      return {
        type: 'Feature' as const,
        properties: { conf: c.confidence, n: c.business_count },
        geometry: { type: 'Polygon' as const, coordinates: [[...ring, ring[0]]] },
      }
    })
    ;(map.getSource('cells') as maplibregl.GeoJSONSource)
      ?.setData({ type: 'FeatureCollection', features: feats })
    const b = new maplibregl.LngLatBounds()
    for (const f of feats) for (const c of f.geometry.coordinates[0]) b.extend(c as [number, number])
    if (feats.length) map.fitBounds(b, { padding: 26, duration: 300, maxZoom: 16 })
  }, [cells, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    // A coordinate carrying records from both feeds is marked 'both' — that is
    // the corroboration story at point level, and it is invisible in a list.
    const bySpot = new Map<string, Set<string>>()
    for (const p of places) {
      const k = `${p.lat.toFixed(6)},${p.lon.toFixed(6)}`
      if (!bySpot.has(k)) bySpot.set(k, new Set())
      bySpot.get(k)!.add(p.source)
    }
    const feats = places.map(p => {
      const spot = bySpot.get(`${p.lat.toFixed(6)},${p.lon.toFixed(6)}`)!
      return {
        type: 'Feature' as const,
        properties: {
          key: pointKey(p),
          src: spot.size > 1 ? 'both' : p.source,
          dup: p.duplicate_suspected ? 1 : 0,
        },
        geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
      }
    })
    ;(map.getSource('pts') as maplibregl.GeoJSONSource)
      ?.setData({ type: 'FeatureCollection', features: feats })
  }, [places, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    map.setPaintProperty('veil', 'background-opacity', layers.bright ? VEIL_BRIGHT : VEIL_DIM)
    map.setLayoutProperty('cell-fill', 'visibility', layers.hexes ? 'visible' : 'none')
    for (const id of ['pts', 'pt-halo', 'pt-ring']) {
      map.setLayoutProperty(id, 'visibility', layers.points ? 'visible' : 'none')
    }
  }, [layers, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !map.getLayer('pt-halo')) return
    const active = hovered ?? focused ?? ''
    map.setFilter('pt-halo', ['==', ['get', 'key'], active])
    map.setFilter('pt-ring', ['==', ['get', 'key'], focused ?? ''])
  }, [hovered, focused, ready])

  return (
    <>
      <div className="rc-map-wrap">
        <div className="rc-map" ref={ref} />
        <MapControls map={mapRef.current} />
      </div>
      {err && <p className="rc-note rc-warn">{err}</p>}
    </>
  )
}

/** Where this report was opened from, so it can offer a way back.
 *
 *  Only ever used to build an internal /compare link from two coordinate
 *  pairs — never to redirect to a URL taken from a parameter. */
function compareOrigin() {
  const p = new URLSearchParams(window.location.search)
  if (p.get('from') !== 'compare') return null
  const parse = (v: string | null) => {
    if (!v) return null
    const [lat, lon] = v.split(',').map(Number)
    return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null
  }
  const a = parse(p.get('ca'))
  const b = parse(p.get('cb'))
  return a || b ? { a, b } : null
}



function Scrubber({ series, category, loading, total, overtureCount }
: {
  series?: Series; category: string; loading?: boolean
  total?: number; overtureCount?: number
}) {
  // The corrected series is what gets plotted when one exists. When correction
  // was withheld, raw is plotted and the mandatory reason is shown ABOVE it —
  // raw then contains a known uncorrected artifact.
  const plotted = series?.series_corrected?.length ? series.series_corrected : series?.series_raw
  const n = plotted?.length ?? 0

  // Index is stored as "offset from the END", so switching category lands on
  // the latest snapshot of the new series instead of an index borrowed from
  // the old one. The previous version kept an absolute index: picking a
  // category with a longer history and coming back left idx past the end of
  // the shorter one, which silently produced an undefined point — a blank
  // readout and no highlighted marker.
  const [fromEnd, setFromEnd] = useState(0)
  const idx = n ? Math.min(Math.max(n - 1 - fromEnd, 0), n - 1) : 0

  const [chartRef, W, chartNode] = useWidth<HTMLDivElement>()
  const H = 132, PAD = { l: 8, r: 8, t: 14, b: 14 }

  const geom = useMemo(() => {
    if (!plotted || plotted.length < 2 || W < 40) return null
    const vals = plotted.map(p => p.value)
    const min = Math.min(...vals), max = Math.max(...vals)
    const span = max - min || 1
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b
    const pts = plotted.map((p, j) => ({
      x: PAD.l + (j / (plotted.length - 1)) * iw,
      y: PAD.t + ih - ((p.value - min) / span) * ih,
      p,
    }))
    return { pts, min, max }
  }, [plotted, W])

  // One control, not two: the chart IS the scrubber.
  const pick = (clientX: number) => {
    if (!geom || !chartNode.current) return
    const rel = clientX - chartNode.current.getBoundingClientRect().left
    let best = 0, bestD = Infinity
    geom.pts.forEach((pt, j) => {
      const d = Math.abs(pt.x - rel)
      if (d < bestD) { bestD = d; best = j }
    })
    setFromEnd(n - 1 - best)
  }
  const dragging = useRef(false)

  if (!series) {
    return (
      <section className="rc-series">
        <h2>{cap(category)}s over time</h2>
        <p className="rc-note">
          {loading
            ? 'loading…'
            : `No snapshot history covers ${category} in this catchment. That is missing history, not a count of zero.`}
        </p>
      </section>
    )
  }

  const cur = plotted?.[idx]
  const excluded = series.excluded_from_corrected ?? []

  return (
    <section className="rc-series">
      <div className="rc-series-head">
        <h2>{cap(category)}s listed by Overture, over time</h2>
        {/* Date and value live in the header — the readout under the old
            slider was a third thing to look at for one number. */}
        {cur && (
          <span className="rc-series-cur num">
            {/* NEVER a bare number here. The headline count includes Foursquare
                and this line cannot; printing "10" beside a card reading "18"
                and explaining the gap in prose loses every time. "10 of 18"
                puts the relationship on screen where it cannot be misread. */}
            <span className="rc-series-v">{fmt(cur.value)}</span>
            {total != null && cur.value <= total && (
              <span className="rc-series-of">of {fmt(total)}</span>
            )}
            <span className="rc-series-scope">Overture only</span>
            <span className="rc-dot">·</span>
            {cur.as_of}
            {cur.status === 'artifact_suspected' && (
              <span className="rc-warn"> · bulk-import step</span>
            )}
          </span>
        )}
      </div>

      {/* THE TWO NUMBERS ARE NOT THE SAME QUANTITY. Stated before the chart,
          not in a footnote, because a reader who sees 65 above and 32 here
          will otherwise conclude one of them is wrong. */}
      {series.comparable_to_latest_metric === false && series.scope_note && (
        <p className="rc-callout rc-callout-tight" title={series.scope_note}>
          Overture publishes history, Foursquare does not — this line tracks
          {overtureCount != null && total != null
            ? ` ${fmt(overtureCount)} of the ${fmt(total)} records`
            : ' only part of the count'}.
        </p>
      )}
      {series.correction_status === 'withheld_too_short' && (
        <p className="rc-callout rc-callout-warn">
          {series.series_corrected_unavailable_reason}
        </p>
      )}
      {series.divergence_note && (
        <p className="rc-callout rc-callout-warn">{series.divergence_note}</p>
      )}

      {n < 2 && (
        <p className="rc-callout">
          Only <span className="num">{n}</span> snapshot{n === 1 ? '' : 's'} available
          for {category} here — too few to plot a line. A two-point trend is not a trend.
        </p>
      )}
      <div
        className={'rc-chart' + (n < 2 ? ' rc-chart-empty' : '')} ref={chartRef}
        onPointerDown={e => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); pick(e.clientX) }}
        onPointerMove={e => { if (dragging.current) pick(e.clientX) }}
        onPointerUp={e => { dragging.current = false; e.currentTarget.releasePointerCapture(e.pointerId) }}
        onPointerCancel={() => { dragging.current = false }}
      >
        {geom && (
          <svg width={W} height={H}>
            <line
              className="rc-cursor"
              x1={geom.pts[idx].x} x2={geom.pts[idx].x} y1={PAD.t - 8} y2={H - PAD.b + 6}
            />
            <polyline className="rc-line" points={geom.pts.map(p => `${p.x},${p.y}`).join(' ')} />
            {geom.pts.map((pt, j) => (
              <circle
                key={pt.p.snapshot_id}
                cx={pt.x} cy={pt.y} r={j === idx ? 4.5 : 2.6}
                className={
                  'rc-pt' +
                  (pt.p.status === 'artifact_suspected' ? ' rc-pt-artifact' : '') +
                  (j === idx ? ' rc-pt-on' : '')
                }
              />
            ))}
          </svg>
        )}
      </div>
      {geom && (
        <div className="rc-axis num">
          <span>{plotted![0].as_of}</span>
          <span className="rc-dim">
            low <span className="num">{fmt(geom.min)}</span>
            <span className="rc-dot">·</span>
            high <span className="num">{fmt(geom.max)}</span>
          </span>
          <span>{plotted![n - 1].as_of}</span>
        </div>
      )}
      <div className="rc-legend-line">
        {/* The key only appears when there is something for it to key. A legend
            for a marker that is not on the chart, sitting next to the words
            "no import artifact detected", reads as a contradiction. */}
        {series.artifact_suspected_count > 0 ? (
          <>
            <span className="rc-key rc-key-artifact" /> bulk-import step, marked not smoothed
            {series.correction_status === 'applied' && (
              <>
                <span className="rc-dot">·</span>
                {excluded.length} earlier point(s) dropped from the corrected series
              </>
            )}
          </>
        ) : (
          <>No bulk-import artifact detected — the whole series is plotted as measured.</>
        )}
      </div>

      <p className="rc-note num">
        {(() => {
          const shape = describeShape(plotted ?? [])
          const g = series.growth_pct_corrected ?? series.growth_pct_raw
          const first = plotted?.[0]?.value
          const last = plotted?.[plotted.length - 1]?.value
          return (
            <>
              {/* "-66.7%" on a series that went 3 -> 1 is noise dressed as a
                  finding. Under the base floor, say what actually happened. */}
              {first != null && first < MIN_PCT_BASE ? (
                <>
                  First to last: <span className="num">{fmt(first)}</span> to{' '}
                  <span className="num">{fmt(last)}</span> over the period
                  <span className="rc-dim" title={`Percentages are suppressed below a base of ${MIN_PCT_BASE}: a change of one record on a base of ${fmt(first)} would read as a large percentage.`}>
                    {' '}— too small a base for a percentage
                  </span>
                </>
              ) : (
                <>
                  First to last: <span className="num">{fmt(g, 1)}%</span>
                  {shape && <span className="rc-dim"> — {shape}</span>}
                </>
              )}
            </>
          )
        })()}
        {series.gap_note && (
          <>
            <span className="rc-dot">·</span>
            {/* The full explanation of the permanently lost release lives in
                the tooltip. As a block of amber it dominated a section that is
                otherwise mostly good news. */}
            <span className="rc-gap" title={series.gap_note}>1 snapshot missing</span>
          </>
        )}
        {series.member_cells_with_artifacts > 0 && (
          <>
            <span className="rc-dot">·</span>
            <span className="rc-dim" title="A member cell shows an import step that is not visible in this aggregate. Advisory only — it does not truncate this series.">
              {series.member_cells_with_artifacts} of {series.member_cells_total} cells
              flagged
            </span>
          </>
        )}
      </p>
    </section>
  )
}





function Verdict({ data, category, competitors, series }
: {
  data: Report; category: string; competitors?: Metric; series?: Series
}) {
  const lim = data.limitations
  const pop = data.metrics.find(m => m.metric === 'population')
  const perOutlet = data.metrics.find(m => m.metric.startsWith('people_per_competitor'))
  const dir = series?.growth_pct_corrected

  // TWO PARAGRAPHS, NOT A CHECKLIST. The honesty lands harder terse: a long
  // bulleted disclaimer reads as documentation and gets skipped, which defeats
  // the point of putting it on the screen at all.
  return (
    <section className="rc-verdict">
      <div className="rc-verdict-col">
        <h2>What we can say</h2>
        <p>
          The sources list{' '}
          <span className="num">{fmt(competitors?.value)}</span> {category}
          {competitors?.value === 1 ? '' : 's'} here
          {competitors?.value_per_land_km2 != null && (
            <> — <span className="num">{fmt(competitors.value_per_land_km2, 1)}</span> per
              land km², which is the figure to compare between locations</>
          )}
          . About <span className="num">{fmt(pop?.value)}</span> people live inside the
          catchment on a <span className="num">{pop?.as_of?.slice(0, 4)}</span> count
          {perOutlet?.value != null && (
            <>, or <span className="num">{fmt(perOutlet.value)}</span> people per outlet</>
          )}
          .
        </p>
        <p>
          {/* The trajectory was sitting unused on the saturation card. It is the
              one forward-looking thing this dataset produces, and the study
              found it only fires where there is room to build. */}
          The ground is <strong>{data.context.saturation_class.toLowerCase()}</strong> at{' '}
          <span className="num">{fmt(data.context.builtup_pct, 0)}%</span> built up
          {data.context.saturation_class !== 'SATURATED' && data.context.builtup_growth_pct >= 5 ? (
            <>, and building: <span className="num">+{fmt(data.context.builtup_growth_pct, 0)}%</span>{' '}
              more built-up area since 2015. Room to build, and it is being built.</>
          ) : data.context.saturation_class === 'SATURATED' ? (
            <> — built out, so flat construction here says nothing about commercial change.</>
          ) : (
            <>, with little measured construction since 2015.</>
          )}
          {dir != null && (
            <> The listed count has moved <span className="num">{fmt(dir, 1)}%</span> since
              the last bulk import — a direction, not a formation rate.</>
          )}
        </p>
      </div>
      <div className="rc-verdict-col">
        <h2>What we can't</h2>
        <p>
          Nothing here measures <strong>foot traffic</strong> or <strong>rents</strong> —
          no free source covers either, and a busy street and a dead one look identical
          in this data. The count is not exact: duplicates are disclosed rather than
          merged, worth{' '}
          <span className="num">{lim.duplicate_inflation_pct_range[0]}–{lim.duplicate_inflation_pct_range[1]}%</span>{' '}
          inflation, and the two feeds are not independent — Foursquare is itself an
          Overture contributor, so agreement is weaker evidence than it looks.
        </p>
        <p>
          Positions are block-level, not addresses:{' '}
          <span className="num">{lim.position_error_median_m} m</span> median disagreement
          between sources and <span className="num">{lim.position_error_p90_m} m</span> at
          p90. Fine for a {data.query.radius_m} m catchment, useless for "this side of the
          street".
        </p>
        {lim.notes && lim.notes.length > 0 && (
          <p className="rc-note">{lim.notes.join(' ')}</p>
        )}
      </div>
    </section>
  )
}

/** Skeletons mirror the real layout so nothing moves when data lands. */
function ReportSkeleton() {
  return (
    <div className="rc-skel">
      <section className="rc-cards">
        {[0, 1, 2, 3].map(i => (
          <div className="rc-card" key={i}>
            <Skel w={110} h={12} />
            <div style={{ margin: '10px 0 12px' }}><Skel w={90} h={26} /></div>
            <Skel w="80%" h={11} />
            <div style={{ marginTop: 6 }}><Skel w="60%" h={11} /></div>
          </div>
        ))}
      </section>
      <div className="rc-main">
        <section className="rc-panel"><Skel w="100%" h="100%" r={8} /></section>
        <div className="rc-side">
          <section className="rc-places"><Skel w="100%" h="100%" r={8} /></section>
        </div>
      </div>
    </div>
  )
}


/** Why a two-source metric can read "single source".
 *  The catchment confidence is the WEAKEST of its cells, which is correct and
 *  looks like a contradiction beside a two-source list unless the split is
 *  spelled out. So spell it out. */
function saveLayers(l: Layers) {
  try { sessionStorage.setItem(LAYER_KEY, JSON.stringify(l)) } catch { /* private mode */ }
}

export function loadLayers(): Layers {
  try {
    const raw = sessionStorage.getItem(LAYER_KEY)
    return raw ? { ...DEFAULT_LAYERS, ...JSON.parse(raw) } : DEFAULT_LAYERS
  } catch { return DEFAULT_LAYERS }
}

/** The catchment as the API actually assembled it — the h3 k-ring, not a smooth
 *  circle. Plus the records inside it, because 12 cafes strung along one street
 *  and 12 spread evenly are the same number and completely different places,
 *  and a cafe pinned in the Nile is invisible in a list and obvious on a map. */

function emptyFC() {
  return { type: 'FeatureCollection' as const, features: [] }
}

/** Three toggles and a legend, always visible. */

/** Point counts by source, for the map legend. A coordinate carrying both
 *  feeds is counted once as "both" rather than twice. */
function sourceTally(places: PlaceRec[]) {
  const spots = new Map<string, Set<string>>()
  for (const p of places) {
    const k = `${p.lat.toFixed(6)},${p.lon.toFixed(6)}`
    if (!spots.has(k)) spots.set(k, new Set())
    spots.get(k)!.add(p.source)
  }
  let overture = 0, fsq = 0, both = 0, dup = 0
  for (const p of places) {
    const set = spots.get(`${p.lat.toFixed(6)},${p.lon.toFixed(6)}`)!
    if (set.size > 1) both++
    else if (p.source === 'overture') overture++
    else fsq++
    if (p.duplicate_suspected) dup++
  }
  return { overture, fsq, both, dup }
}
/** Width of an element, tracked live. The chart draws in PIXEL space so its
 *  point markers stay circular — a viewBox stretched with
 *  preserveAspectRatio="none" turns every circle into an ellipse.
 *
 *  CALLBACK REF, NOT useEffect([]), AND ZERO IS IGNORED.
 *  The previous version observed ref.current once on mount. Switching category
 *  briefly unmounted the chart (see below), and a DETACHED element fires
 *  ResizeObserver with a 0x0 contentRect on removal — so width went to 0, the
 *  observer stayed bound to the dead node, and the remounted chart was never
 *  measured again. Width stuck at 0, the geometry memo bailed out, and the
 *  chart rendered as an empty box while the header still showed data.
 *  A callback ref re-attaches the observer to whatever node is current, and a
 *  0 reading is discarded because an element that is actually zero-width has
 *  nothing to draw anyway. */
function useWidth<T extends HTMLElement>() {
  const node = useRef<T | null>(null)
  const obs = useRef<ResizeObserver | null>(null)
  const [w, setW] = useState(0)

  const ref = useCallback((el: T | null) => {
    obs.current?.disconnect()
    obs.current = null
    node.current = el
    if (!el) return
    const ro = new ResizeObserver(es => {
      const width = es[0].contentRect.width
      if (width > 0) setW(width)
    })
    ro.observe(el)
    obs.current = ro
    const initial = el.getBoundingClientRect().width
    if (initial > 0) setW(initial)
  }, [])

  useEffect(() => () => obs.current?.disconnect(), [])
  return [ref, w, node] as const
}

/** First-to-last percent is technically true and frequently useless: a series
 *  that dips to 1 and recovers to 4 reports 0.0% and tells the reader nothing.
 *  Describe the path when the endpoints hide it. */
function describeShape(pts: Point[]): string | null {
  if (pts.length < 3) return null
  const first = pts[0].value, last = pts[pts.length - 1].value
  let lo = pts[0], hi = pts[0]
  for (const p of pts) {
    if (p.value < lo.value) lo = p
    if (p.value > hi.value) hi = p
  }
  const yr = (p: Point) => p.as_of.slice(0, 4)
  if (pts.every(p => p.value === first)) return 'flat throughout'
  const same = Math.abs(last - first) < 0.5
  if (same && lo.value < first) return `ends where it started, after a dip to ${lo.value} in ${yr(lo)}`
  if (same && hi.value > first) return `ends where it started, after a peak of ${hi.value} in ${yr(hi)}`
  if (hi.value > Math.max(first, last)) return `peaked at ${hi.value} in ${yr(hi)} along the way`
  if (lo.value < Math.min(first, last)) return `bottomed at ${lo.value} in ${yr(lo)} along the way`
  return null
}

function TableSkeleton() {
  return (
    <div className="rc-table-skel">
      {Array.from({ length: 8 }, (_, i) => (
        <div className="rc-table-skel-row" key={i}>
          <Skel w={30} h={12} /><Skel w={`${45 + (i % 4) * 10}%`} h={12} />
          <Skel w={48} h={12} /><Skel w={70} h={12} />
        </div>
      ))}
    </div>
  )
}
