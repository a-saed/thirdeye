/*
 * COMPARE — two locations, one row per metric.
 *
 * ORGANISED BY METRIC, NOT BY LOCATION. Two report cards side by side leave
 * the reader doing the comparison themselves, scanning back and forth to pair
 * up figures. A row per metric pairs them once, in the layout.
 *
 * NO OVERALL WINNER, EVER. This screen says where each location leads and
 * stops. It does not know the rent, the lease terms, the landlord, or why
 * someone wants that street — and a composite score would launder those
 * unknowns into a number that looks decisive. Per-metric leadership is a
 * measurement; an overall verdict would be an opinion wearing its clothes.
 *
 * TWO LOCATIONS MAXIMUM. Three columns stop being readable, and human
 * pairwise comparison degrades past two anyway.
 *
 * Both sides are fetched from GET /report — the same endpoint the single
 * report uses, called twice. A dedicated compare endpoint would be a second
 * place for the aggregation rules to live and drift.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { cellToBoundary } from 'h3-js'
import 'maplibre-gl/dist/maplibre-gl.css'
import { setMeta } from '../components/meta'
import Footer from '../components/Footer'
import CopyLink from '../components/CopyLink'
import { useFetch, useDelayed, Skel, ErrorBox } from '../components/async'
import '../tokens.css'
import './compare.css'

const DARK_MATTER = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const VEIL = 0.45
const CATEGORIES = ['cafe', 'restaurant', 'pharmacy', 'grocery', 'gym'] as const
// The middle ring. See the note on the k state below.
const DEFAULT_K = 1
/* Below this, report counts rather than a percentage. */
const MIN_PCT_BASE = 10
const RINGS = [
  { k: 0, label: '~0.1 km²', walk: '~2 min' },
  { k: 1, label: '~0.9 km²', walk: '~6 min' },
  { k: 2, label: '~2.3 km²', walk: '~10 min' },
] as const

type Conf = 'corroborated' | 'single_source' | 'unavailable'
const CONF_LABEL: Record<Conf, string> = {
  corroborated: 'Corroborated', single_source: 'Single source', unavailable: 'No data',
}
const CONF_GLYPH: Record<Conf, string> = {
  corroborated: '●', single_source: '○', unavailable: '–',
}
const CONF_RANK: Record<Conf, number> = { corroborated: 2, single_source: 1, unavailable: 0 }

interface Metric {
  metric: string; value: number
  value_per_land_km2: number | null
  confidence: Conf; contributing_sources: string[]; as_of: string
  direction_of_good: string; native_res: number
  cells_total: number; cells_by_confidence: Record<string, number>
}
interface Report {
  query: { lat: number; lon: number; radius_m: number; category: string; k_ring: number }
  context: {
    land_area_km2: number; builtup_pct: number; builtup_growth_pct: number
    saturation_class: string; cell_count: number; h3_res: number; k_ring: number
    cells: { h3: string; confidence: Conf }[]
  }
  metrics: Metric[]
  limitations: {
    duplicate_inflation_pct_range: [number, number]
    position_error_median_m: number; position_error_p90_m: number
    independence_caveat: string; notes?: string[]
  }
}
interface Loc { lat: number; lon: number; name?: string }

const fmt = (v: number | null | undefined, d = 0) =>
  v == null || Number.isNaN(v)
    ? '—'
    : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
const cap = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t)

function parseLoc(raw: string | null): Loc | null {
  if (!raw) return null
  const [a, b] = raw.split(',').map(Number)
  return Number.isFinite(a) && Number.isFinite(b) ? { lat: a, lon: b } : null
}

/** Locations the user has already looked at, so picking B does not require
 *  hunting the map again. Written by the report screen. */
/** Metres between two points. Small-angle equirectangular is plenty at the
 *  ~200 m scale this is used for. */
function metres(a: Loc, b: Loc) {
  const dy = (a.lat - b.lat) * 111320
  const dx = (a.lon - b.lon) * 111320 * Math.cos((a.lat * Math.PI) / 180)
  return Math.hypot(dx, dy)
}

/** Locations already looked at, most recent first.
 *
 *  DEDUPED BY PROXIMITY, not by exact coordinate. Three clicks a few metres
 *  apart in the same neighbourhood are one place to a reader, and listing
 *  "El Agouza" three times makes the picker look broken. Same-cell pins also
 *  give near-identical reports, so keeping the newest loses nothing. */
function recents(): Loc[] {
  try {
    const raw: Loc[] = JSON.parse(localStorage.getItem('thirdeye.recent') || '[]')
    const out: Loc[] = []
    for (const r of raw) {
      if (!out.some(k => metres(k, r) < 200)) out.push(r)
      if (out.length === 6) break
    }
    return out
  } catch { return [] }
}

export default function Compare() {
  const p = new URLSearchParams(window.location.search)
  const [a, setA] = useState<Loc | null>(parseLoc(p.get('a')))
  const [b, setB] = useState<Loc | null>(parseLoc(p.get('b')))
  const [category, setCategory] = useState(() => {
    const c = p.get('category')
    return c && (CATEGORIES as readonly string[]).includes(c) ? c : 'cafe'
  })
  // DEFAULT_K, not zero. Number(null) is 0, so "no k in the URL" silently
  // became the single-cell catchment — and at k=0 a shop 30 m past the cell
  // boundary disappears entirely, which reads as the product being unreliable
  // when it is a resolution artifact. Cross-source position error is 58 m at
  // p90; the middle ring is the smallest one that survives it.
  const [k, setK] = useState(() => {
    const raw = p.get('k')
    if (raw === null) return DEFAULT_K
    const v = Number(raw)
    return Number.isInteger(v) && v >= 0 && v <= 2 ? v : DEFAULT_K
  })

  useEffect(() => {
    const both = a?.name && b?.name ? `${a.name} vs ${b.name}` : null
    setMeta(
      both ? `${both} — Third Eye` : 'Compare locations — Third Eye',
      both
        ? `${both}, side by side: businesses, population and construction, each figure sourced and dated.`
        : 'Two locations side by side: businesses, population and construction, each figure sourced and dated.',
    )
  }, [a, b])

  // EACH SIDE IS INDEPENDENT. One location can be outside coverage, or its
  // request can fail, while the other is fine — collapsing both into a single
  // request would throw away a perfectly good half of the screen.
  // Same category and the same catchment for both, always: a comparison across
  // different areas or categories is not a comparison.
  const reqA = useFetch<Report>(
    a ? `/api/report?lat=${a.lat}&lon=${a.lon}&k=${k}&category=${category}` : null,
    'Location A')
  const reqB = useFetch<Report>(
    b ? `/api/report?lat=${b.lat}&lon=${b.lon}&k=${k}&category=${category}` : null,
    'Location B')
  const ra = reqA.state.s === 'ok' ? reqA.state.data : null
  const rb = reqB.state.s === 'ok' ? reqB.state.data : null

  useEffect(() => {
    const q = new URLSearchParams()
    if (a) q.set('a', `${a.lat},${a.lon}`)
    if (b) q.set('b', `${b.lat},${b.lon}`)
    q.set('k', String(k)); q.set('category', category)
    window.history.replaceState(null, '', `/compare?${q}`)
  }, [a, b, k, category])

  // Names are labels only, fetched best-effort.
  useEffect(() => {
    for (const [loc, set] of [[a, setA], [b, setB]] as const) {
      if (!loc || loc.name) continue
      fetch(`/api/geocode/reverse?lat=${loc.lat}&lon=${loc.lon}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => d?.name && set({ ...loc, name: d.name }))
        .catch(() => {})
    }
  }, [a, b])

  const rows = useMemo(() => buildRows(ra, rb, category), [ra, rb, category])

  return (
    <div className="cmp">
      <header className="cmp-head">
        <a href="/" className="cmp-brand">
          <img src="/brand/lockup-compact-teal.svg" height={30} alt="Third Eye" />
        </a>
        <div className="cmp-controls">
          <div className="cmp-chips">
            {CATEGORIES.map(c => (
              <button key={c} className={'cmp-chip' + (c === category ? ' on' : '')}
                      onClick={() => setCategory(c)}>{cap(c)}</button>
            ))}
          </div>
          <div className="cmp-rings">
            <span className="cmp-eyebrow">Catchment</span>
            {RINGS.map(r => (
              <button key={r.k} className={'cmp-ring' + (r.k === k ? ' on' : '')}
                      onClick={() => setK(r.k)}>
                <span>{r.label}</span><span className="cmp-ring-w">{r.walk}</span>
              </button>
            ))}
          </div>
        </div>
      </header>

      {!a && !b && (
        <section className="cmp-intro">
          <h1>Compare two locations</h1>
          <p>
            Pick two points and see them measured against each other —
            competitors, people within reach, and how fast each area is being
            built. Same catchment, same category, side by side.
          </p>
        </section>
      )}

      <div className="cmp-share">
        <CopyLink label="Copy comparison link" />
      </div>

      <div className="cmp-slots">
        {/* Each side carries the CURRENT query into its report, so a
            comparison made at Pharmacy / 2.3 km² opens a report showing
            pharmacies at 2.3 km² rather than the defaults. */}
        <Slot label="A" loc={a} report={ra} onPick={setA} req={reqA}
              category={category} k={k} other={b} />
        <Slot label="B" loc={b} report={rb} onPick={setB} req={reqB}
              category={category} k={k} other={a} />
      </div>

      {/* With nothing chosen, the space goes to a coverage map: someone arriving
          from the home CTA knows roughly where they are looking, not what to
          type into a search box. */}
      {!a && !b && <PickerMap onPick={setA} />}

      {(a || b) && (
        <div className="cmp-minis">
          {a && <MiniMap loc={a} report={ra} side="a" category={category} />}
          {b && <MiniMap loc={b} report={rb} side="b" category={category} />}
        </div>
      )}

      {rows.length > 0 && (
        <section className="cmp-rows">
          <div className="cmp-rowhead">
            <span />
            <span className="cmp-side">{a?.name ?? 'A'}</span>
            <span />
            <span className="cmp-side cmp-side-b">{b?.name ?? 'B'}</span>
          </div>
          {rows.map(r => <Row key={r.key} r={r} />)}
          <p className="cmp-foot">
            Each row says which location leads on that measure and by how much.
            There is deliberately no overall score: nothing here knows the rent,
            the lease or why you want that street, and a single number would
            hide those behind a decimal point.
          </p>
        </section>
      )}

      {(ra || rb) && <Caveats ra={ra} rb={rb} />}
      <Footer />
    </div>
  )
}

/* ---------- one location slot ---------- */

interface Cov { in_coverage: boolean; confidence?: Conf; businesses?: number }

/** Coverage for a candidate, resolved before it is chosen.
 *
 *  Picking a location and only then discovering that four rows read "no data"
 *  is the frustrating version of this screen. One call per candidate against
 *  the res-8 store, which is a map lookup on the server. */
function useCoverage(points: Loc[]) {
  const [cov, setCov] = useState<Record<string, Cov>>({})
  const key = (l: Loc) => `${l.lat.toFixed(5)},${l.lon.toFixed(5)}`
  useEffect(() => {
    let cancelled = false
    for (const p of points) {
      const k = key(p)
      if (cov[k]) continue
      fetch(`/api/coverage?lat=${p.lat}&lon=${p.lon}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (d && !cancelled) setCov(c => ({ ...c, [k]: d })) })
        .catch(() => {})
    }
    return () => { cancelled = true }
  }, [points.map(key).join('|')])
  return (l: Loc) => cov[key(l)]
}

function CoverageTag({ c }: { c?: Cov }) {
  if (!c) return <span className="cmp-cov cmp-cov-wait">checking…</span>
  if (!c.in_coverage) {
    return <span className="cmp-cov cmp-cov-out">no coverage — no data for this region</span>
  }
  if (!c.businesses) {
    return <span className="cmp-cov cmp-cov-thin">in coverage · no business data in this cell</span>
  }
  return (
    <span className="cmp-cov cmp-cov-in">
      {CONF_LABEL[(c.confidence ?? 'unavailable') as Conf].toLowerCase()} ·{' '}
      {fmt(c.businesses)} businesses in this cell
    </span>
  )
}

/** The link back into a full report for one side.
 *
 *  A plain <a> with the right query string — the report already reads every
 *  parameter it needs from the URL, so this needs no new logic. `from`, `ca`
 *  and `cb` let the report rebuild the comparison for its back link without
 *  carrying a whole URL in a parameter, which would be an open redirect
 *  waiting to be pointed somewhere else.
 */
function reportHref(loc: Loc, other: Loc | null, category: string, k: number) {
  const q = new URLSearchParams({
    lat: String(loc.lat), lon: String(loc.lon),
    k: String(k), category, from: 'compare',
    ca: `${loc.lat},${loc.lon}`,
  })
  if (other) q.set('cb', `${other.lat},${other.lon}`)
  return `/report?${q}`
}

function Slot({ label, loc, report, onPick, req, category, k, other }: {
  label: string; loc: Loc | null; report: Report | null; onPick: (l: Loc) => void
  req: { state: { s: string; message?: string }; retry: () => void }
  category: string; k: number; other: Loc | null
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<any[]>([])
  const rec = useMemo(recents, [open])
  const candidates = useMemo(
    () => [...hits.slice(0, 6).map((h: any) => ({ lat: h.lat, lon: h.lon })), ...rec],
    [hits, rec],
  )
  const coverage = useCoverage(candidates)

  useEffect(() => {
    const t = q.trim()
    if (t.length < 3) { setHits([]); return }
    const id = setTimeout(() => {
      fetch(`/api/geocode/search?q=${encodeURIComponent(t)}`)
        .then(r => (r.ok ? r.json() : { results: [] }))
        .then(d => setHits(d.results ?? []))
        .catch(() => setHits([]))
    }, 400)
    return () => clearTimeout(id)
  }, [q])

  return (
    <div className={'cmp-slot' + (label === 'B' ? ' cmp-slot-b' : '')}>
      <div className="cmp-slot-tag">{label}</div>
      {loc ? (
        <>
          <div className="cmp-slot-name">{loc.name ?? 'Selected location'}</div>
          <div className="cmp-slot-sub num">
            {loc.lat.toFixed(5)}, {loc.lon.toFixed(5)}
            {report && (
              <>
                <span className="cmp-dot">·</span>
                {fmt(report.context.land_area_km2, 2)} km²
              </>
            )}
            {req.state.s === 'loading' && (
              <><span className="cmp-dot">·</span><Skel w={54} h={10} /></>
            )}
          </div>
          {req.state.s === 'error' && (
            <ErrorBox message={req.state.message!} onRetry={req.retry} compact />
          )}
        </>
      ) : (
        <div className="cmp-slot-empty">No location chosen</div>
      )}
      <div className="cmp-slot-actions">
        {loc ? (
          <a className="cmp-open" href={reportHref(loc, other, category, k)}>
            Open full report →
          </a>
        ) : (
          <span className="cmp-open cmp-open-off"
                title="Choose a location for this side first — there is nothing to report on yet.">
            Open full report →
          </span>
        )}
        <button className="cmp-change" onClick={() => setOpen(o => !o)}>
          {loc ? 'Change' : 'Choose'}
        </button>
      </div>

      {open && (
        <div className="cmp-picker">
          <input
            className="cmp-search" value={q} autoFocus
            placeholder="Search a place or business"
            onChange={e => setQ(e.target.value)}
          />
          {hits.length > 0 && (
            <ul className="cmp-hits">
              {hits.slice(0, 6).map((h, i) => (
                <li key={i}>
                  <button onClick={() => { onPick({ lat: h.lat, lon: h.lon, name: h.name }); setOpen(false) }}>
                    <span>{h.name}</span>
                    <span className="cmp-hit-sub">{h.detail}</span>
                    <CoverageTag c={coverage({ lat: h.lat, lon: h.lon })} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {rec.length > 0 && (
            <>
              <div className="cmp-eyebrow cmp-rec-h">Recent reports</div>
              <ul className="cmp-hits">
                {rec.map((r, i) => (
                  <li key={i}>
                    <button onClick={() => { onPick(r); setOpen(false) }}>
                      <span>{r.name ?? 'Location'}</span>
                      <span className="cmp-hit-sub num">
                        {r.lat.toFixed(4)}, {r.lon.toFixed(4)}
                      </span>
                      <CoverageTag c={coverage(r)} />
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="cmp-pick-note">
            Or open a report and use “Compare with this”.
          </p>
        </div>
      )}
    </div>
  )
}

/* ---------- the rows ---------- */

interface RowData {
  key: string; label: string
  a?: { v: number; conf: Conf; asOf: string }
  b?: { v: number; conf: Conf; asOf: string }
  direction: string          // higher | lower | context
  unit?: string
  digits?: number
  note?: string
}

function buildRows(ra: Report | null, rb: Report | null, category: string): RowData[] {
  if (!ra && !rb) return []
  const pick = (r: Report | null, name: string) => {
    const m = r?.metrics.find(x => x.metric === name)
    return m ? { v: m.value, conf: m.confidence, asOf: m.as_of, dir: m.direction_of_good } : undefined
  }
  const perArea = (r: Report | null, name: string) => {
    const m = r?.metrics.find(x => x.metric === name)
    return m?.value_per_land_km2 != null
      ? { v: m.value_per_land_km2, conf: m.confidence, asOf: m.as_of }
      : undefined
  }
  const biz = `business_count.${category}`
  const ppc = `people_per_competitor.${category}`

  const rows: RowData[] = [
    { key: 'biz', label: `${cap(category)} competitors`,
      a: pick(ra, biz), b: pick(rb, biz),
      direction: pick(ra, biz)?.dir ?? pick(rb, biz)?.dir ?? 'lower' },
    { key: 'density', label: `${cap(category)}s per land km²`,
      a: perArea(ra, biz), b: perArea(rb, biz), direction: 'lower', digits: 1 },
    { key: 'pop', label: 'Population',
      a: pick(ra, 'population'), b: pick(rb, 'population'),
      direction: pick(ra, 'population')?.dir ?? 'higher' },
    { key: 'ppc', label: `People per ${category}`,
      a: pick(ra, ppc), b: pick(rb, ppc),
      direction: pick(ra, ppc)?.dir ?? 'higher' },
  ]

  // Context rows: no leader, because "more built up" is not better or worse.
  if (ra || rb) {
    rows.push({
      key: 'built', label: 'Built up', direction: 'context', unit: '%', digits: 1,
      a: ra ? { v: ra.context.builtup_pct, conf: 'corroborated', asOf: '' } : undefined,
      b: rb ? { v: rb.context.builtup_pct, conf: 'corroborated', asOf: '' } : undefined,
    })
    rows.push({
      key: 'growth', label: 'Built-up growth since 2015', direction: 'higher',
      unit: '%', digits: 0,
      note: 'The study found this signal only fires where there is room to build; a saturated area reads flat because it is built out.',
      a: ra ? { v: ra.context.builtup_growth_pct, conf: 'corroborated', asOf: '' } : undefined,
      b: rb ? { v: rb.context.builtup_growth_pct, conf: 'corroborated', asOf: '' } : undefined,
    })
  }
  return rows.filter(r => r.a || r.b)
}

function Row({ r }: { r: RowData }) {
  const av = r.a?.v, bv = r.b?.v
  const both = av != null && bv != null
  const max = Math.max(Math.abs(av ?? 0), Math.abs(bv ?? 0)) || 1
  const aPct = ((av ?? 0) / max) * 100
  const bPct = ((bv ?? 0) / max) * 100

  // DIRECTION COMES FROM THE API AND IS NEVER INVERTED HERE. More population
  // is good, more competitors is bad; getting this backwards would silently
  // reverse the meaning of every bar on the screen.
  let leader: 'a' | 'b' | null = null
  if (both && r.direction !== 'context' && av !== bv) {
    const aBetter = r.direction === 'higher' ? av! > bv! : av! < bv!
    leader = aBetter ? 'a' : 'b'
  }

  // A percentage needs a base big enough to carry one. 3 vs 1 is "200%", which
  // dresses a difference of two records as a finding. Below the floor the row
  // states the counts and lets the reader judge.
  const smallBase = both && Math.min(av!, bv!) < MIN_PCT_BASE
  const diff = both && Math.min(av!, bv!) > 0 && !smallBase
    ? Math.abs(av! - bv!) / Math.min(av!, bv!) * 100
    : null

  // A comparison is only as strong as its weaker side.
  const weaker = both && r.a && r.b && r.a.conf !== r.b.conf
    ? (CONF_RANK[r.a.conf] < CONF_RANK[r.b.conf] ? 'A' : 'B')
    : null

  return (
    <div className="cmp-row">
      <div className="cmp-label">
        {r.label}
        {r.direction !== 'context' && (
          <span className="cmp-dir" title={`Direction of good comes from the API: ${r.direction} is better for this metric.`}>
            {r.direction === 'higher' ? 'more is better' : 'fewer is better'}
          </span>
        )}
      </div>

      <div className={'cmp-val cmp-val-a' + (leader === 'a' ? ' lead' : '')} data-side="A">
        <span className="num">{fmt(av, r.digits ?? 0)}{r.unit}</span>
        {r.a && <ConfDot c={r.a.conf} />}
      </div>

      {/* A BAR IS A COMPARISON. With one value the other side renders empty and
          the full-width bar reads as "A scores maximum", which is the opposite
          of "we have nothing to compare it to". */}
      {both ? (
        <div className="cmp-bars">
          <div className="cmp-bar-side">
            <div className={'cmp-bar cmp-bar-a' + (leader === 'a' ? ' lead' : '')}
                 style={{ width: `${aPct}%` }} />
          </div>
          <div className="cmp-bar-mid" />
          <div className="cmp-bar-side">
            <div className={'cmp-bar cmp-bar-b' + (leader === 'b' ? ' lead' : '')}
                 style={{ width: `${bPct}%` }} />
          </div>
        </div>
      ) : (
        <div className="cmp-bars cmp-bars-none"><span className="cmp-bar-mid" /></div>
      )}

      <div className={'cmp-val cmp-val-b' + (leader === 'b' ? ' lead' : '')} data-side="B">
        <span className="num">{fmt(bv, r.digits ?? 0)}{r.unit}</span>
        {r.b && <ConfDot c={r.b.conf} />}
      </div>

      <div className="cmp-verdict">
        {/* One side missing a metric is NOT a zero and must never read as one:
            it means no source covers that category there. Saying which side is
            missing keeps a bare dash from looking like a bad score. */}
        {!both && (av != null || bv != null) && (
          <span className="cmp-nodata">
            no data for {av == null ? 'A' : 'B'} — not a count of zero
          </span>
        )}
        {leader && diff != null && (
          <span>
            <strong>{leader === 'a' ? 'A' : 'B'}</strong> leads by{' '}
            <span className="num">{fmt(diff, 0)}%</span>
          </span>
        )}
        {leader && diff == null && smallBase && (
          <span title={`Below ${MIN_PCT_BASE}, a percentage says more about the base than the difference.`}>
            <strong>{leader === 'a' ? 'A' : 'B'}</strong> leads,{' '}
            <span className="num">{fmt(av, r.digits ?? 0)}</span> to{' '}
            <span className="num">{fmt(bv, r.digits ?? 0)}</span>
          </span>
        )}
        {r.direction === 'context' && <span className="cmp-dim">context, not better or worse</span>}
        {weaker && (
          <span className="cmp-weak" title="A catchment takes the weakest confidence among its cells. Where the two sides differ, the comparison rests on the weaker one.">
            {weaker} is the weaker evidence
          </span>
        )}
        {r.note && <span className="cmp-dim" title={r.note}>ⓘ</span>}
      </div>
    </div>
  )
}

function ConfDot({ c }: { c: Conf }) {
  return (
    <span className={`cmp-conf cmp-conf-${c}`} title={CONF_LABEL[c]}>
      {CONF_GLYPH[c]}
    </span>
  )
}

/** Coverage map for the empty state: pick A by clicking, the same way the
 *  home screen works. Arriving here from the home CTA with two blank cards and
 *  a search box asks the user to name a place; a map lets them point at one. */
function PickerMap({ onPick }: { onPick: (l: Loc) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const showSkel = useDelayed(loading)

  useEffect(() => {
    if (!ref.current) return
    const cs = getComputedStyle(document.documentElement)
    const t = (k: string) => cs.getPropertyValue(k).trim()
    const map = new maplibregl.Map({
      container: ref.current, style: DARK_MATTER,
      center: [31.05, 30.15], zoom: 7.2, attributionControl: { compact: true },
    })
    map.on('error', e => setErr((e as any)?.error?.message || 'Basemap unavailable.'))
    map.on('load', async () => {
      try {
        map.addLayer({
          id: 'veil', type: 'background',
          paint: { 'background-color': t('--canvas'), 'background-opacity': VEIL },
        })
        const res = await fetch('/coverage-res8.geojson')
        if (!res.ok) throw new Error(`coverage layer: HTTP ${res.status}`)
        const fc = await res.json()
        map.addSource('cov', { type: 'geojson', data: fc })
        map.addLayer({
          id: 'cov', type: 'fill', source: 'cov',
          paint: {
            'fill-color': ['match', ['get', 'conf'],
              'corroborated', t('--accent'), 'single_source', t('--amber'), t('--map-no-data')],
            'fill-opacity': ['match', ['get', 'conf'],
              'corroborated', 0.85, 'single_source', 0.38, 0.58],
          },
        })
        map.getCanvas().style.cursor = 'crosshair'
        setLoading(false)
      } catch (e: any) {
        setErr(`Coverage layer failed: ${e.message}.`)
        setLoading(false)
      }
    })
    map.on('click', e => onPick({ lat: e.lngLat.lat, lon: e.lngLat.lng }))
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); map.remove() }
  }, [])

  return (
    <div className="cmp-picker-map-wrap">
      <div className="cmp-picker-map" ref={ref} />
      {showSkel && loading && <div className="cmp-map-skel"><Skel w="100%" h="100%" r={8} /></div>}
      {err
        ? <p className="cmp-picker-cap cmp-picker-err">{err} You can still search above.</p>
        : <p className="cmp-picker-cap">
            Click anywhere in the shaded area to set location A, or use the
            search on either card.
          </p>}
    </div>
  )
}

/* ---------- one small map per location ---------- */

/** TWO LOCAL MAPS, NOT ONE WIDE ONE.
 *
 *  A single map framing both points sat at city zoom: two specks of hexagon
 *  separated by 15 km of empty. The distance between the candidates is not the
 *  question — what surrounds each one is. Side by side at local zoom, each map
 *  shows its own catchment and its own business points, and the two are
 *  directly comparable because they are at the same scale.
 */
function MiniMap({ loc, report, side, category }: {
  loc: Loc; report: Report | null; side: 'a' | 'b'; category: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const [pts, setPts] = useState<{ lat: number; lon: number; src: string }[]>([])

  useEffect(() => {
    let cancelled = false
    fetch(`/api/places?lat=${loc.lat}&lon=${loc.lon}&k=${report?.context.k_ring ?? 1}` +
          `&category=${category}&limit=600`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!d || cancelled) return
        setPts(d.places.map((p: any) => ({ lat: p.lat, lon: p.lon, src: p.source })))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [loc, category, report?.context.k_ring])

  useEffect(() => {
    if (!ref.current) return
    const cs = getComputedStyle(document.documentElement)
    const map = new maplibregl.Map({
      container: ref.current, style: DARK_MATTER,
      center: [loc.lon, loc.lat], zoom: 14, attributionControl: { compact: true },
    })
    mapRef.current = map
    map.on('load', () => {
      map.addLayer({
        id: 'veil', type: 'background',
        paint: {
          'background-color': cs.getPropertyValue('--canvas').trim(),
          'background-opacity': VEIL,
        },
      })
      map.addSource('cells', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addSource('pts', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: 'cells', type: 'fill', source: 'cells',
        paint: {
          'fill-color': side === 'a' ? cs.getPropertyValue('--accent').trim() : '#8B9DF0',
          'fill-opacity': 0.18,
        },
      })
      map.addLayer({
        id: 'cells-line', type: 'line', source: 'cells',
        paint: { 'line-color': 'rgba(255,255,255,0.22)', 'line-width': 0.8 },
      })
      map.addLayer({
        id: 'pts', type: 'circle', source: 'pts',
        paint: {
          'circle-radius': 3,
          'circle-color': ['match', ['get', 'src'], 'overture', '#6BA8D8', '#C77FD0'],
          'circle-opacity': 0.85,
          'circle-stroke-width': 0.5, 'circle-stroke-color': 'rgba(0,0,0,0.5)',
        },
      })
      new maplibregl.Marker({
        color: side === 'a' ? cs.getPropertyValue('--accent').trim() : '#8B9DF0', scale: 0.6,
      }).setLngLat([loc.lon, loc.lat]).addTo(map)
      setReady(true)
    })
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); map.remove() }
  }, [loc.lat, loc.lon, side])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    const feats = (report?.context.cells ?? []).map(c => {
      const ring = cellToBoundary(c.h3, true)
      return {
        type: 'Feature' as const, properties: {},
        geometry: { type: 'Polygon' as const, coordinates: [[...ring, ring[0]]] },
      }
    })
    ;(map.getSource('cells') as maplibregl.GeoJSONSource)
      ?.setData({ type: 'FeatureCollection', features: feats })
    if (feats.length) {
      const b = new maplibregl.LngLatBounds()
      for (const f of feats) for (const c of f.geometry.coordinates[0]) b.extend(c as [number, number])
      map.fitBounds(b, { padding: 18, duration: 300, maxZoom: 16 })
    }
  }, [report, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    ;(map.getSource('pts') as maplibregl.GeoJSONSource)?.setData({
      type: 'FeatureCollection',
      features: pts.map(p => ({
        type: 'Feature' as const, properties: { src: p.src },
        geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
      })),
    })
  }, [pts, ready])

  return (
    <div className="cmp-mini">
      <div className="cmp-mini-map" ref={ref} />
      <div className="cmp-mini-cap">
        <span className={'cmp-mini-tag cmp-mini-' + side}>{side.toUpperCase()}</span>
        {loc.name ?? 'Location'}
        <span className="cmp-dot">·</span>
        <span className="num">{fmt(pts.length)}</span> {category}
        {pts.length === 1 ? '' : 's'} plotted
      </div>
    </div>
  )
}

/* ---------- caveats, which apply to both ---------- */

function Caveats({ ra, rb }: { ra: Report | null; rb: Report | null }) {
  const lim = (ra ?? rb)!.limitations
  const notes = [...new Set([...(ra?.limitations.notes ?? []), ...(rb?.limitations.notes ?? [])])]
  return (
    <section className="cmp-caveats">
      <h2>What we can't say — about either of them</h2>
      <p>
        Nothing here measures <strong>foot traffic</strong> or <strong>rents</strong>;
        no free source covers either, and a busy street and a dead one look
        identical in this data. Counts are not exact — duplicates are disclosed
        rather than merged, worth{' '}
        <span className="num">{lim.duplicate_inflation_pct_range[0]}–{lim.duplicate_inflation_pct_range[1]}%</span>{' '}
        inflation on both sides — and the two feeds are not independent, so
        agreement is weaker evidence than it looks.
      </p>
      <p>
        Positions are block-level:{' '}
        <span className="num">{lim.position_error_median_m} m</span> median
        disagreement between sources,{' '}
        <span className="num">{lim.position_error_p90_m} m</span> at p90. Fine for
        comparing catchments, useless for comparing two sides of one street.
      </p>
      {notes.length > 0 && <p className="cmp-dim">{notes.join(' ')}</p>}
    </section>
  )
}
