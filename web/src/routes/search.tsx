import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import ConfBadge from '../components/ConfBadge'
import Footer from '../components/Footer'
import { fmt, cap } from '../lib/format'
import { searchDimPaint, searchHitPaint, searchFocusPaint } from '../map/paint.mjs'
import type { Metric, SearchResp, SearchRow } from '../lib/types'
import './search.css'

/* AREA SEARCH — the reverse of the report.
 *
 * The report answers "what is here". This answers "where is it like this",
 * which is the question a site search actually starts from.
 *
 * THERE IS NO OPPORTUNITY SCORE. Rows are ranked by one metric the user picks
 * and the other filtered metrics sit beside it. Blending population, competition
 * and growth into a single number would hide the weighting and assert a view of
 * what matters that belongs to the user, not to us.
 *
 * The map is the primary view: it paints EVERY match, while the list shows a
 * capped page. Painting only the page would draw a smaller answer than the
 * counts describe.
 */

const DARK_MATTER = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const VEIL_ALPHA = 0.45

const CATEGORIES = ['cafe', 'restaurant', 'pharmacy', 'grocery', 'gym']
const GOVERNORATES = ['Cairo', 'Giza', 'Qalyubiya', 'Alexandria']
const SATURATION = ['GREENFIELD', 'DEVELOPING', 'SATURATED']

/** Sort keys, with the label the user reads. Competitor-based sorts need a
 *  category, which the API enforces — this only avoids offering the dead end. */
const SORTS: { key: string; label: string; needsCategory?: boolean }[] = [
  { key: 'population', label: 'Population' },
  { key: 'population_per_land_km2', label: 'Population per land km²' },
  { key: 'competitors', label: 'Competitors', needsCategory: true },
  { key: 'people_per_competitor', label: 'People per outlet', needsCategory: true },
  { key: 'builtup_pct', label: 'Built-up %' },
  { key: 'builtup_growth_pct', label: 'Built-up growth since 2015' },
]

/** Metric name -> the words a reader sees. The API names are stable ids. */
function label(name: string): string {
  if (name.startsWith('business_count.')) return `${cap(name.split('.')[1])} outlets`
  if (name.startsWith('people_per_competitor.')) return 'People per outlet'
  const m: Record<string, string> = {
    population: 'Population',
    builtup_pct: 'Built-up %',
    builtup_pct_2015: 'Built-up % in 2015',
    builtup_growth_pct: 'Growth since 2015',
  }
  return m[name] ?? name
}

function unit(name: string): string {
  if (name === 'builtup_pct' || name === 'builtup_pct_2015') return '%'
  if (name === 'builtup_growth_pct') return '%'
  return ''
}

function digits(name: string): number {
  return name.startsWith('builtup') ? 1 : 0
}

type Filters = {
  category: string
  governorate: string
  saturation: string
  confidence: string
  population_min: string; population_max: string
  competitors_min: string; competitors_max: string
  people_per_competitor_min: string; people_per_competitor_max: string
  builtup_pct_min: string; builtup_pct_max: string
  growth_pct_min: string
  include_uninhabited: boolean
  include_distorted: boolean
  sort: string
  order: string
}

const EMPTY: Filters = {
  category: '', governorate: '', saturation: '', confidence: '',
  population_min: '', population_max: '',
  competitors_min: '', competitors_max: '',
  people_per_competitor_min: '', people_per_competitor_max: '',
  builtup_pct_min: '', builtup_pct_max: '',
  growth_pct_min: '',
  include_uninhabited: false, include_distorted: false,
  sort: 'population', order: '',
}

/** Filters live in the URL so a search is shareable, the same as report and
 *  compare. Reading them back is what makes "find areas like this" work. */
function fromURL(): Filters {
  const p = new URLSearchParams(window.location.search)
  const f = { ...EMPTY }
  for (const k of Object.keys(EMPTY) as (keyof Filters)[]) {
    const v = p.get(k)
    if (v == null) continue
    if (k === 'include_uninhabited' || k === 'include_distorted') {
      (f[k] as boolean) = v === '1'
    } else {
      (f[k] as string) = v
    }
  }
  return f
}

function toQuery(f: Filters): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) {
    if (v === '' || v === false) continue
    p.set(k, v === true ? '1' : String(v))
  }
  return p.toString()
}

export default function Search() {
  const [f, setF] = useState<Filters>(fromURL)
  /* FILTERS COLLAPSE ON A PHONE.
     Measured at 375x667: this page ran to 17,639px — 26 screens — and the
     nine-field form sat between the header and the first result, so reaching
     a result meant scrolling past every control that produced it. Desktop is
     unaffected: there the panel is a column with its own space. */
  const [filtersOpen, setFiltersOpen] = useState(false)
  /* sort and order are always set, so they are not "filters" for the purpose
     of telling someone how many they have applied. */
  const activeFilters = (Object.keys(EMPTY) as (keyof Filters)[])
    .filter(k => k !== 'sort' && k !== 'order' && f[k] !== EMPTY[k]).length
  const [data, setData] = useState<SearchResp | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)

  const mapEl = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [mapReady, setMapReady] = useState(0)
  const painted = useRef<Set<string>>(new Set())

  const qs = useMemo(() => toQuery(f), [f])
  const set = useCallback(
    <K extends keyof Filters>(k: K, v: Filters[K]) => setF(p => ({ ...p, [k]: v })), [])

  // The URL follows the filters, without a history entry per keystroke.
  useEffect(() => {
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)
  }, [qs])

  // Fetch, debounced: typing in a number field should not fire a scan per digit.
  useEffect(() => {
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      setBusy(true); setErr('')
      fetch(`/api/search?${qs}`, { signal: ctrl.signal })
        .then(async r => {
          const j = await r.json()
          if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`)
          return j as SearchResp
        })
        .then(d => { setData(d); setBusy(false) })
        .catch(e => {
          if (e.name === 'AbortError') return
          // A failed search says so. It never renders as "no results", which
          // would read as a measured answer.
          setErr(e.message || 'search failed'); setData(null); setBusy(false)
        })
    }, 250)
    return () => { clearTimeout(t); ctrl.abort() }
  }, [qs])

  // ---- map
  useEffect(() => {
    if (!mapEl.current) return
    const cs = getComputedStyle(document.documentElement)
    const t = (k: string) => cs.getPropertyValue(k).trim()
    const map = new maplibregl.Map({
      container: mapEl.current, style: DARK_MATTER,
      center: [31.05, 30.15], zoom: 7.2, attributionControl: false,
    })
    mapRef.current = map
    map.on('error', e => setErr((e as any)?.error?.message || 'basemap unavailable'))
    map.on('load', async () => {
      try {
        map.addLayer({
          id: 'veil', type: 'background',
          paint: { 'background-color': t('--canvas'), 'background-opacity': VEIL_ALPHA },
        })
        const res = await fetch('/coverage-res8.geojson')
        if (!res.ok) throw new Error(`coverage layer: HTTP ${res.status}`)
        const fc = await res.json()
        // promoteId makes the h3 string the feature id, so a result set is
        // painted with setFeatureState instead of a filter holding 4,000 ids.
        map.addSource('cells', { type: 'geojson', data: fc, promoteId: 'h3' })
        const tk = { accent: t('--accent'), amber: t('--amber'), noData: t('--map-no-data') }
        map.addLayer({ id: 'search-dim', type: 'fill', source: 'cells', paint: searchDimPaint(tk) as any })
        map.addLayer({ id: 'search-hit', type: 'fill', source: 'cells', paint: searchHitPaint(tk) as any })
        map.addLayer({ id: 'search-focus', type: 'line', source: 'cells', paint: searchFocusPaint(tk) as any })
        setMapReady(v => v + 1)
      } catch (e: any) {
        setErr(e.message || 'map layer failed')
      }
    })
    return () => { map.remove(); mapRef.current = null }
  }, [])

  // Repaint matches. Clears the previous set rather than accumulating, so a
  // narrowed search cannot leave stale cells lit.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady || !map.getSource('cells')) return
    for (const h3 of painted.current) map.setFeatureState({ source: 'cells', id: h3 }, { hit: false })
    painted.current.clear()
    if (!data) return
    const conf = new Map(data.results.map(r => [r.h3, r.confidence]))
    for (const h3 of data.matched_h3) {
      map.setFeatureState({ source: 'cells', id: h3 },
        { hit: true, conf: conf.get(h3) ?? 'single_source' })
      painted.current.add(h3)
    }
  }, [data, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady || !map.getSource('cells')) return
    for (const h3 of painted.current) map.setFeatureState({ source: 'cells', id: h3 }, { focus: false })
    if (focus) map.setFeatureState({ source: 'cells', id: focus }, { focus: true })
  }, [focus, mapReady])

  const sortOpts = SORTS.filter(s => !s.needsCategory || f.category)
  const activeSort = data?.sort

  return (
    <div className="sr">
      <header className="sr-head">
        <div>
          <a className="sr-back" href="/">← Third Eye</a>
          <h1>Area search</h1>
          <p className="sr-sub">
            Find cells matching criteria, rather than starting from a place you
            already know. Ranked by one metric you choose — there is no blended
            score.
          </p>
        </div>
      </header>

      <div className="sr-body">
        <aside className={'sr-filters' + (filtersOpen ? ' is-open' : '')}>
          {/* Hidden above 900px, where the panel is always open and this
              would just be a button that does nothing useful. */}
          <button
            className="sr-filters-toggle"
            onClick={() => setFiltersOpen(o => !o)}
            aria-expanded={filtersOpen}
          >
            <span>
              Filters
              {activeFilters > 0 && (
                <span className="sr-filters-count">{activeFilters}</span>
              )}
            </span>
            <span className="sr-filters-caret" aria-hidden="true">
              {filtersOpen ? '▴' : '▾'}
            </span>
          </button>
          <div className="sr-filters-body">
          <Field label="Category">
            <select value={f.category} onChange={e => {
              const v = e.target.value
              setF(p => ({
                ...p, category: v,
                // A competitor sort with no category is a dead end; fall back
                // rather than sending a request the API will reject.
                sort: !v && (p.sort === 'competitors' || p.sort === 'people_per_competitor')
                  ? 'population' : p.sort,
              }))
            }}>
              <option value="">Any / none</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{cap(c)}</option>)}
            </select>
          </Field>

          <Field label="Region">
            <select value={f.governorate} onChange={e => set('governorate', e.target.value)}>
              <option value="">Whole coverage</option>
              {GOVERNORATES.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </Field>

          <Field label="Saturation">
            <select value={f.saturation} onChange={e => set('saturation', e.target.value)}>
              <option value="">Any</option>
              {SATURATION.map(s => <option key={s} value={s}>{cap(s.toLowerCase())}</option>)}
            </select>
          </Field>

          <Range label="Population" lo={f.population_min} hi={f.population_max}
            onLo={v => set('population_min', v)} onHi={v => set('population_max', v)} />

          <Range label="Competitors" disabled={!f.category}
            hint={!f.category ? 'Pick a category first' : undefined}
            lo={f.competitors_min} hi={f.competitors_max}
            onLo={v => set('competitors_min', v)} onHi={v => set('competitors_max', v)} />

          <Range label="People per outlet" disabled={!f.category}
            hint={!f.category ? 'Pick a category first' : undefined}
            lo={f.people_per_competitor_min} hi={f.people_per_competitor_max}
            onLo={v => set('people_per_competitor_min', v)}
            onHi={v => set('people_per_competitor_max', v)} />

          <Range label="Built-up %" lo={f.builtup_pct_min} hi={f.builtup_pct_max}
            onLo={v => set('builtup_pct_min', v)} onHi={v => set('builtup_pct_max', v)} />

          <Field label="Built-up growth since 2015, at least">
            <input type="number" inputMode="numeric" placeholder="%"
              value={f.growth_pct_min} onChange={e => set('growth_pct_min', e.target.value)} />
          </Field>

          <Field label="Confidence">
            <select value={f.confidence} onChange={e => set('confidence', e.target.value)}>
              <option value="">Any</option>
              <option value="single_source">Single source or better</option>
              <option value="corroborated">Corroborated only</option>
            </select>
          </Field>

          <label className="sr-check">
            <input type="checkbox" checked={f.include_uninhabited}
              onChange={e => set('include_uninhabited', e.target.checked)} />
            Include uninhabited cells
          </label>
          <label className="sr-check">
            <input type="checkbox" checked={f.include_distorted}
              onChange={e => set('include_distorted', e.target.checked)} />
            Include density-distorted cells
          </label>

          <hr className="sr-rule" />

          <Field label="Rank by">
            <select value={f.sort} onChange={e => set('sort', e.target.value)}>
              {sortOpts.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Order">
            <select value={f.order} onChange={e => set('order', e.target.value)}>
              <option value="">Best first</option>
              <option value="desc">Highest first</option>
              <option value="asc">Lowest first</option>
            </select>
          </Field>
          {activeSort && (
            <p className="sr-dir">
              Ranked by <strong>{label(activeSort.metric)}</strong>
              {activeSort.direction_of_good !== 'context' && (
                <> — {activeSort.direction_of_good === 'higher' ? 'more is better' : 'fewer is better'}</>
              )}.
            </p>
          )}
          <button className="sr-reset" onClick={() => setF({ ...EMPTY })}>Reset filters</button>
          </div>
        </aside>

        <main className="sr-main">
          <div className="sr-map" ref={mapEl} />

          <section className="sr-results">
            {err && <p className="sr-err">Search failed: {err}</p>}
            {busy && !data && <p className="sr-muted">Scanning the coverage grid…</p>}

            {data && (
              <>
                <div className="sr-counts">
                  <strong>{fmt(data.counts.matched)}</strong> cells match
                  {data.counts.capped && <> — showing the top {fmt(data.counts.returned)}</>}
                  <span className="sr-of">
                    {' '}searched {fmt(data.counts.cells_searchable)} of{' '}
                    {fmt(data.counts.cells_in_coverage)} cells
                  </span>
                </div>

                {data.notes.length > 0 && (
                  <ul className="sr-notes">
                    {data.notes.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                )}

                {data.empty_reason && (
                  <p className="sr-empty">{data.empty_reason}</p>
                )}

                <ol className="sr-list">
                  {data.results.map(r => (
                    <Row key={r.h3} r={r} sortMetric={data.sort.metric}
                      category={f.category}
                      onEnter={() => setFocus(r.h3)} onLeave={() => setFocus(null)} />
                  ))}
                </ol>
              </>
            )}
          </section>
        </main>
      </div>
      <Footer />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="sr-field">
      <span className="sr-label">{label}</span>
      {children}
    </label>
  )
}

function Range({ label, lo, hi, onLo, onHi, disabled, hint }: {
  label: string; lo: string; hi: string
  onLo: (v: string) => void; onHi: (v: string) => void
  disabled?: boolean; hint?: string
}) {
  return (
    <div className={`sr-field${disabled ? ' sr-off' : ''}`}>
      <span className="sr-label">{label}</span>
      <div className="sr-range">
        <input type="number" inputMode="numeric" placeholder="min" value={lo}
          disabled={disabled} onChange={e => onLo(e.target.value)} />
        <span aria-hidden="true">–</span>
        <input type="number" inputMode="numeric" placeholder="max" value={hi}
          disabled={disabled} onChange={e => onHi(e.target.value)} />
      </div>
      {hint && <span className="sr-hint">{hint}</span>}
    </div>
  )
}

function Row({ r, sortMetric, category, onEnter, onLeave }: {
  r: SearchRow; sortMetric: string; category: string
  onEnter: () => void; onLeave: () => void
}) {
  const by = new Map(r.metrics.map(m => [m.metric, m]))
  const primary = by.get(sortMetric)
  const rest = r.metrics.filter(m => m.metric !== sortMetric)
  // The report link carries the category through, so the row and the report it
  // opens describe the same thing.
  const href = `/report?lat=${r.lat}&lon=${r.lon}${category ? `&category=${category}` : ''}`

  return (
    <li className="sr-row" onMouseEnter={onEnter} onMouseLeave={onLeave} onFocus={onEnter} onBlur={onLeave}>
      <div className="sr-row-head">
        <div>
          <a className="sr-name" href={href}>
            {r.place_name || `${r.governorate} · ${r.h3.slice(0, 8)}…`}
          </a>
          <div className="sr-meta">
            {r.governorate} · {cap(r.saturation_class.toLowerCase())}
            {r.density_distorted && <> · <span className="sr-flag">density-distorted</span></>}
            {r.population_stale && <> · <span className="sr-flag">population stale</span></>}
          </div>
        </div>
        <ConfBadge c={r.confidence} size="sm" />
      </div>

      {primary && (
        <div className="sr-primary">
          <span className="sr-primary-v">
            {fmt(primary.value, digits(primary.metric))}{unit(primary.metric)}
          </span>
          <span className="sr-primary-l">{label(primary.metric)}</span>
        </div>
      )}

      <dl className="sr-other">
        {rest.map(m => <Cell key={m.metric} m={m} />)}
      </dl>
    </li>
  )
}

function Cell({ m }: { m: Metric }) {
  // A measured zero is shown as 0 and said to be measured. fmt() renders
  // missing as "—"; the two must never look alike.
  const isMeasuredZero = m.value === 0 && m.cells_none_present > 0
  return (
    <div className="sr-cellv">
      <dt>{label(m.metric)}</dt>
      <dd title={isMeasuredZero
        ? 'Measured zero: this cell has business data and none of it is in this category.'
        : undefined}>
        {fmt(m.value, digits(m.metric))}{unit(m.metric)}
        {isMeasuredZero && <span className="sr-zero"> measured</span>}
      </dd>
    </div>
  )
}
