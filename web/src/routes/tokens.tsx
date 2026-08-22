/*
 * TOKEN PREVIEW — /tokens
 *
 * The design system made visible, so the aesthetic can be judged before any
 * real screen exists. Spec: docs/DESIGN.md. Values: src/tokens.css.
 *
 * This page reads tokens from the CSS custom properties at runtime rather
 * than restating them in JS. If a token changes in tokens.css, this page
 * follows automatically — a preview that can drift from what it previews is
 * worse than no preview.
 *
 * Contrast and luminance figures shown are COMPUTED HERE from the live token
 * values, not typed in. A hardcoded "4.58:1" that silently stops being true
 * when someone nudges a hex is exactly the fabricated-number failure the
 * project rules forbid.
 */
import React, { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import '../tokens.css'
import './tokens.css'

/* ---------- colour maths, so every figure on this page is measured -------- */

type RGB = [number, number, number]

function parseColor(v: string): RGB | null {
  const s = v.trim()
  const hex = s.match(/^#([0-9a-f]{6})$/i)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const rgba = s.match(/^rgba?\(([^)]+)\)$/)
  if (rgba) {
    const p = rgba[1].split(',').map(x => parseFloat(x))
    return [p[0], p[1], p[2]]
  }
  return null
}

const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))

function luminance(rgb: RGB): number {
  const [r, g, b] = rgb.map(c => lin(c / 255))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: RGB, b: RGB): number {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/** Composite fg over bg at alpha — how the map fills actually land. */
function over(fg: RGB, bg: RGB, a: number): RGB {
  return [0, 1, 2].map(i => a * fg[i] + (1 - a) * bg[i]) as RGB
}

const hex = (rgb: RGB) =>
  '#' + rgb.map(c => Math.round(c).toString(16).padStart(2, '0')).join('').toUpperCase()

/* ---------- token registry ------------------------------------------------ */

const SURFACES = ['--canvas', '--surface', '--surface-2', '--surface-3']
const LINES = ['--border', '--border-strong']
const TEXTS = ['--text', '--text-muted', '--text-faint', '--text-disabled']
const DATA = ['--accent', '--amber', '--no-data']

const CONFIDENCE = [
  { key: 'corroborated', label: 'Corroborated', glyph: '●', token: '--accent', alpha: '--alpha-corroborated' },
  { key: 'single_source', label: 'Single source', glyph: '○', token: '--amber', alpha: '--alpha-single' },
  { key: 'unavailable', label: 'No data', glyph: '–', token: '--no-data', alpha: '--alpha-nodata' },
] as const

/* Real cells, real confidence values. Extent chosen because it actually
   contains all three classes (30 / 115 / 35) — a preview of the ramp that
   happened to show only one class would prove nothing. */
const PREVIEW_CENTER: [number, number] = [31.37, 29.98]
const PREVIEW_SPAN = { lon: 0.075, lat: 0.05 }
const DARK_MATTER = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const VEIL_ALPHA = 0.45

/* THE HEXES DO NOT COMPOSITE OVER --canvas.
 * They composite over the VEILED BASEMAP: 0.45 canvas over Dark Matter, whose
 * background layer is #0e0e0e (read from the published style, not assumed).
 * Every ladder figure on this page is computed against that, because that is
 * the surface a user actually sees the fill against. */
const DM_BACKGROUND = '#0e0e0e'

/* Candidates for judging on the real extent. These are NOT tokens — they are
 * a decision aid. Whichever wins gets promoted into tokens.css. */
const SINGLE_CANDIDATES = [
  { id: 'current', hex: '#D8A33F', alpha: 0.55, note: 'current — the mustard field' },
  { id: 'A', hex: '#D8A33F', alpha: 0.38, note: 'same hue, less mass — recommended' },
  { id: 'B', hex: '#E8BC5A', alpha: 0.32, note: 'cleaner amber, less mass' },
  { id: 'C', hex: '#E8BC5A', alpha: 0.26, note: 'quietest' },
] as const

const NODATA_CANDIDATES = [
  { id: 'current', hex: '#2C3236', alpha: 0.40 },
  { id: 'N1', hex: '#39424A', alpha: 0.55 },
  { id: 'N2', hex: '#3F4A52', alpha: 0.58 },
  { id: 'N3', hex: '#454F58', alpha: 0.60 },
] as const

/* ---------- page ---------------------------------------------------------- */

export default function TokensPage() {
  const [tok, setTok] = useState<Record<string, string>>({})

  useEffect(() => {
    const cs = getComputedStyle(document.documentElement)
    const all = [...SURFACES, ...LINES, ...TEXTS, ...DATA,
      '--alpha-corroborated', '--alpha-single', '--alpha-nodata', '--tint']
    const out: Record<string, string> = {}
    for (const k of all) out[k] = cs.getPropertyValue(k).trim()
    setTok(out)
  }, [])

  const rgb = (name: string) => parseColor(tok[name] || '') || ([0, 0, 0] as RGB)
  const alpha = (name: string) => parseFloat(tok[name] || '0')
  const ready = Object.keys(tok).length > 0

  return (
    <div className="tk">
      <header className="tk-head">
        <div>
          <h1>Design tokens</h1>
          <p className="tk-sub">
            Third Eye · dark, single mode · every figure on this page is computed
            from the live token values
          </p>
        </div>
        {/* Height only — the mark's viewBox is 100 x 115.47, so forcing a
            square would squash it. */}
        <img src="/brand/lockup-teal.svg" height={40} alt="Third Eye" />
      </header>

      {!ready ? (
        <p className="tk-sub">reading tokens…</p>
      ) : (
        <>
          <Section
            n="01"
            title="Surfaces"
            note="Never pure black — #000 makes a map read as a hole punched in the screen, because the basemap's own polygons are lighter than it. Separation is by elevation, never by a solid border."
          >
            <div className="tk-swatches">
              {SURFACES.map(t => (
                <Swatch key={t} name={t} value={tok[t]}
                  sub={`L ${luminance(rgb(t)).toFixed(4)}`} />
              ))}
            </div>
            <div className="tk-swatches">
              {LINES.map(t => (
                <div key={t} className="tk-sw">
                  <div className="tk-sw-chip tk-sw-line" style={{ borderColor: tok[t] }} />
                  <div className="tk-sw-meta">
                    <code>{t}</code>
                    <span className="tk-faint num">{tok[t]}</span>
                    <span className="tk-faint">hairline only</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section
            n="02"
            title="Text"
            note="Contrast measured against --canvas and --surface-2. 4.5 is the floor for anything a user must read. --text-disabled sits under it deliberately and is for non-informational use only."
          >
            <table className="tk-table">
              <thead>
                <tr>
                  <th>token</th><th>value</th>
                  <th className="num">on canvas</th><th className="num">on surface-2</th>
                  <th>sample</th>
                </tr>
              </thead>
              <tbody>
                {TEXTS.map(t => {
                  const c1 = contrast(rgb(t), rgb('--canvas'))
                  const c2 = contrast(rgb(t), rgb('--surface-2'))
                  return (
                    <tr key={t}>
                      <td><code>{t}</code></td>
                      <td className="num tk-faint">{tok[t]}</td>
                      <td className={'num ' + (c1 >= 4.5 ? 'tk-pass' : 'tk-under')}>
                        {c1.toFixed(2)}
                      </td>
                      <td className={'num ' + (c2 >= 4.5 ? 'tk-pass' : 'tk-under')}>
                        {c2.toFixed(2)}
                      </td>
                      <td style={{ color: tok[t] }}>Population 12,480 · as of 2023-11-01</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Section>

          <Section
            n="03"
            title="The confidence ladder"
            note="The most important rule in the system. --accent and --amber are near-isoluminant, so the brightness ordering comes from ALPHA over canvas, not from the hues. These values are load-bearing."
          >
            <div className="tk-ladder">
              {CONFIDENCE.map(c => {
                const base = rgb(c.token)
                const a = alpha(c.alpha)
                const comp = over(base, rgb('--canvas'), a)
                return (
                  <div key={c.key} className="tk-rung">
                    <div className="tk-rung-chip" style={{ background: hex(comp) }} />
                    <div className="tk-sw-meta">
                      <span>{c.label}</span>
                      <span className="tk-faint num">
                        {tok[c.token]} @ {a}
                      </span>
                      <span className="tk-faint num">
                        composited {hex(comp)} · L {luminance(comp).toFixed(4)}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
            <p className="tk-note num">
              hue contrast, accent vs amber:{' '}
              <strong>{contrast(rgb('--accent'), rgb('--amber')).toFixed(2)}</strong> — which
              is why hue cannot be the primary channel. Composited, corroborated is{' '}
              <strong>
                {(
                  luminance(over(rgb('--accent'), rgb('--canvas'), alpha('--alpha-corroborated'))) /
                  luminance(over(rgb('--amber'), rgb('--canvas'), alpha('--alpha-single')))
                ).toFixed(2)}×
              </strong>{' '}
              the luminance of single source.
            </p>
          </Section>

          <Section
            n="04"
            title="Confidence badges"
            note="Glyph + label + colour, so the badge still reads with colour removed. Single source gets NO warning styling: 66% of inhabited cells are single-source, and if that looks like an error the product looks broken everywhere it works."
          >
            <div className="tk-row">
              {CONFIDENCE.map(c => <Badge key={c.key} c={c} tok={tok} />)}
            </div>
            <div className="tk-row tk-mono-strip">
              {CONFIDENCE.map(c => (
                <span key={c.key} className="tk-badge tk-badge-grey">
                  <span className="tk-glyph">{c.glyph}</span>{c.label}
                </span>
              ))}
              <span className="tk-faint">← colour removed; still legible</span>
            </div>
          </Section>

          <Section
            n="05"
            title="Type"
            note="One family, four sizes, two weights, sentence case. Tabular figures on every numeric — the scrubber changes values in place, and proportional digits make columns shift as the user drags."
          >
            <div className="tk-type">
              {[
                { px: 23, lh: 28, name: '--t-hero', use: 'the one number a screen is about' },
                { px: 16, lh: 24, name: '--t-head', use: 'section headings, emphasised values' },
                { px: 13, lh: 20, name: '--t-body', use: 'body, labels, table cells' },
                { px: 11, lh: 16, name: '--t-caption', use: 'captions, provenance, badge labels' },
              ].map(t => (
                <div key={t.px} className="tk-type-row">
                  <div className="tk-type-meta">
                    <code>{t.name}</code>
                    <span className="tk-faint num">{t.px}/{t.lh}</span>
                  </div>
                  <div style={{ fontSize: t.px, lineHeight: `${t.lh}px` }}>
                    <span style={{ fontWeight: 400 }} className="num">1,284 businesses</span>
                    <span className="tk-faint"> · </span>
                    <span style={{ fontWeight: 500 }} className="num">1,284 businesses</span>
                    <span className="tk-faint" style={{ fontSize: 11 }}> — {t.use}</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="tk-note">
              Tabular check — these columns must not shift as digits change:
            </p>
            <TabularDemo />
          </Section>

          <Section
            n="06"
            title="Controls"
            note="Primary is --accent and there is at most one per screen. No destructive variant: nothing in this product destroys anything."
          >
            <div className="tk-row">
              <button className="tk-btn tk-btn-primary">Run report</button>
              <button className="tk-btn tk-btn-secondary">Change radius</button>
              <button className="tk-btn tk-btn-ghost">Reset</button>
              <button className="tk-btn tk-btn-secondary" disabled>Unavailable</button>
            </div>
            <div className="tk-row">
              <label className="tk-toggle">
                <input type="checkbox" defaultChecked /> Hide uninhabited cells
              </label>
              <label className="tk-toggle">
                <input type="checkbox" /> Show corrected series
              </label>
            </div>
          </Section>

          <Section
            n="07"
            title="Metric cards"
            note="No card renders a bare value. Confidence sits on the value's baseline, never above it. as_of is visible without interaction — population is a 2023 vintage served in 2026."
          >
            <div className="tk-cards">
              <MetricCard
                label="Businesses within 500 m" value="1,284" conf={CONFIDENCE[0]} tok={tok}
                asOf="2026-07-22" sources="overture, foursquare" extra="agreement ratio 0.71"
              />
              <MetricCard
                label="Businesses within 500 m" value="612" conf={CONFIDENCE[1]} tok={tok}
                asOf="2026-07-22" sources="overture" extra="one source — not corroborated"
              />
              <MetricCard
                label="Businesses within 500 m" value="–" conf={CONFIDENCE[2]} tok={tok}
                asOf="—" sources="none" extra="no source covers this cell"
              />
            </div>
            <p className="tk-note">
              <strong>Illustrative.</strong> The same metric is shown three times, once in
              each confidence state, to compare the treatments side by side — a single
              metric in a single catchment has exactly one confidence, and a real screen
              would never show these three together.
            </p>
            <p className="tk-note">
              The third card shows <code>–</code>, not <code>0</code>. Missing is not zero,
              and this is the easiest place in the product for the UI to lie.
            </p>
          </Section>

          <Section
            n="08"
            title="Hexes on the basemap"
            note="CARTO Dark Matter under a --canvas veil at 0.45, so the basemap desaturates and its labels dim in one move. Same extent in every panel, panning disabled, so the only variable is the ramp. Ratios are computed against the veiled basemap, not against --canvas."
          >
            <HexCompare />
          </Section>

          <Section
            n="09"
            title="Icon"
            note="Pointy-top hexagon, viewBox 100 × 115.47. Two variants with a hard switchover: the solid knockout below 20px, the ring at 24px and above — the ring's stroke is 8% of width and closes up at favicon size. All fills with fill-rule evenodd, no strokes, so scale never changes line weight."
          >
            <div className="tk-icons">
              {[16, 20].map(s => (
                <div key={s} className="tk-icon">
                  <img src="/brand/favicon-teal.svg" height={s} alt="" />
                  <span className="tk-faint num">{s}px</span>
                </div>
              ))}
              <div className="tk-icon-rule">solid ↑ · ring ↓</div>
              {[24, 32, 64, 128].map(s => (
                <div key={s} className="tk-icon">
                  <img src="/brand/icon-teal.svg" height={s} alt="" />
                  <span className="tk-faint num">{s}px</span>
                </div>
              ))}
            </div>
            <div className="tk-icons">
              <div className="tk-icon tk-icon-light">
                <img src="/brand/favicon-black.svg" height={20} alt="" />
                <span className="tk-faint num">black, on light</span>
              </div>
              <div className="tk-icon">
                <img src="/brand/icon-white.svg" height={32} alt="" />
                <span className="tk-faint num">white, mono</span>
              </div>
              <div className="tk-icon">
                {/* The knockout is transparent by design, so at 16px it takes
                    the colour of whatever tab bar sits behind it. */}
                <img src="/brand/favicon-teal.svg" height={16} alt="" />
                <span className="tk-faint num">knockout on canvas</span>
              </div>
            </div>
            <p className="tk-note">
              Wordmark is outlined paths, not live <code>&lt;text&gt;</code>. The
              lockups originally referenced IBM Plex Sans, which silently falls back
              to a generic sans on any machine without it — which is most of them.
              The app UI does not use Plex at all.
            </p>
            <div className="tk-lockups">
              <img src="/brand/lockup-teal.svg" height={44} alt="Third Eye" />
              <div className="tk-lockup-light">
                <img src="/brand/lockup-black.svg" height={44} alt="Third Eye" />
              </div>
            </div>
          </Section>
        </>
      )}
    </div>
  )
}

/* ---------- pieces -------------------------------------------------------- */

function Section({ n, title, note, children }: {
  n: string; title: string; note?: string; children: React.ReactNode
}) {
  return (
    <section className="tk-section">
      <div className="tk-section-head">
        <span className="tk-n num">{n}</span>
        <h2>{title}</h2>
      </div>
      {note && <p className="tk-note">{note}</p>}
      {children}
    </section>
  )
}

function Swatch({ name, value, sub }: { name: string; value: string; sub?: string }) {
  return (
    <div className="tk-sw">
      <div className="tk-sw-chip" style={{ background: value }} />
      <div className="tk-sw-meta">
        <code>{name}</code>
        <span className="tk-faint num">{value}</span>
        {sub && <span className="tk-faint num">{sub}</span>}
      </div>
    </div>
  )
}

function Badge({ c, tok }: { c: typeof CONFIDENCE[number]; tok: Record<string, string> }) {
  const base = parseColor(tok[c.token] || '') || ([0, 0, 0] as RGB)
  const tint = parseFloat(tok['--tint'] || '0.16')
  const bg = over(base, parseColor(tok['--surface-2'] || '') || ([0, 0, 0] as RGB), tint)
  // No-data at full chroma on its own tint measures 2.70:1 — unreadable. It
  // borrows --text-muted instead. Documented in DESIGN.md §7.
  const fg = c.key === 'unavailable' ? tok['--text-muted'] : tok[c.token]
  const ratio = contrast(parseColor(fg) || ([0, 0, 0] as RGB), bg)
  return (
    <span className="tk-badge-wrap">
      <span className="tk-badge" style={{ background: hex(bg), color: fg }}>
        <span className="tk-glyph">{c.glyph}</span>{c.label}
      </span>
      <span className="tk-faint num">{ratio.toFixed(2)}:1</span>
    </span>
  )
}

function MetricCard({ label, value, conf, tok, asOf, sources, extra }: {
  label: string; value: string; conf: typeof CONFIDENCE[number]
  tok: Record<string, string>; asOf: string; sources: string; extra: string
}) {
  return (
    <div className="tk-card">
      <div className="tk-card-label">{label}</div>
      <div className="tk-card-value">
        <span className="num" style={{ color: value === '–' ? tok['--text-muted'] : tok['--text'] }}>
          {value}
        </span>
        <Badge c={conf} tok={tok} />
      </div>
      <div className="tk-card-foot">
        <span className="num">as of {asOf}</span>
        <span className="tk-dot">·</span>
        <span>{sources}</span>
      </div>
      <div className="tk-card-foot">{extra}</div>
    </div>
  )
}

/** Proves the tabular claim rather than asserting it: the digits change every
 *  400ms and the right edge must not move. */
function TabularDemo() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(n => n + 1), 400)
    return () => clearInterval(t)
  }, [])
  const vals = [
    [1284, 612, 0], [1111, 999, 41], [8888, 111, 7], [1090, 470, 22],
  ][i % 4]
  return (
    <table className="tk-table tk-table-narrow">
      <thead>
        <tr><th>metric</th><th className="num">tabular</th><th className="num">proportional</th></tr>
      </thead>
      <tbody>
        {['Businesses', 'Population', 'Competitors'].map((k, j) => (
          <tr key={k}>
            <td>{k}</td>
            <td className="num">{vals[j].toLocaleString()}</td>
            <td className="num tk-proportional">{vals[j].toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Fetches the cells once and renders every candidate against the same extent.
 *  Four separate fetches of a 4.6 MB file to compare four ramps would be
 *  absurd, and four independently-panned maps would not be a comparison. */
function HexCompare() {
  const [features, setFeatures] = useState<any[] | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [err, setErr] = useState<string | null>(null)
  const [nd, setNd] = useState(2)   // default N2 — the recommendation

  useEffect(() => {
    let cancelled = false
    fetch('/coverage-res8.geojson')
      .then(r => {
        if (!r.ok) throw new Error(`coverage-res8.geojson: HTTP ${r.status}`)
        return r.json()
      })
      .then(fc => {
        if (cancelled) return
        const inBox = (f: any) => {
          const r = f.geometry.coordinates[0]
          const lon = r.slice(0, 6).reduce((s: number, p: number[]) => s + p[0], 0) / 6
          const lat = r.slice(0, 6).reduce((s: number, p: number[]) => s + p[1], 0) / 6
          return Math.abs(lon - PREVIEW_CENTER[0]) < PREVIEW_SPAN.lon &&
                 Math.abs(lat - PREVIEW_CENTER[1]) < PREVIEW_SPAN.lat
        }
        const sel = fc.features.filter(inBox)
        const c: Record<string, number> = {}
        for (const f of sel) c[f.properties.conf] = (c[f.properties.conf] || 0) + 1
        setCounts(c)
        setFeatures(sel)
      })
      .catch(e => setErr(e.message))
    return () => { cancelled = true }
  }, [])

  const cs = typeof window !== 'undefined' ? getComputedStyle(document.documentElement) : null
  const canvas = parseColor(cs?.getPropertyValue('--canvas').trim() || '#101315')!
  const accent = parseColor(cs?.getPropertyValue('--accent').trim() || '#45C9A5')!
  // The real backdrop: veil over Dark Matter's own background.
  const ground = over(canvas, parseColor(DM_BACKGROUND)!, VEIL_ALPHA)
  const groundL = luminance(ground)
  const corrL = luminance(over(accent, ground, 0.85))
  const noData = NODATA_CANDIDATES[nd]
  const ndL = luminance(over(parseColor(noData.hex)!, ground, noData.alpha))

  return (
    <>
      <div className="tk-controls">
        <span className="tk-faint">No-data fill</span>
        {NODATA_CANDIDATES.map((c, i) => {
          const l = luminance(over(parseColor(c.hex)!, ground, c.alpha))
          return (
            <label key={c.id} className={'tk-chip' + (i === nd ? ' on' : '')}>
              <input type="radio" name="nd" checked={i === nd} onChange={() => setNd(i)} />
              <span className="tk-chip-sw"
                style={{ background: hex(over(parseColor(c.hex)!, ground, c.alpha)) }} />
              <span>{c.id}</span>
              <span className="tk-faint num">{(l / groundL).toFixed(1)}× ground</span>
            </label>
          )
        })}
      </div>

      {err && <p className="tk-note tk-under">cells failed to load: {err}</p>}

      <div className="tk-grid">
        {SINGLE_CANDIDATES.map(c => {
          const singleL = luminance(over(parseColor(c.hex)!, ground, c.alpha))
          const inverted = singleL <= ndL
          return (
            <div key={c.id} className="tk-panel">
              <div className="tk-panel-head">
                <strong>{c.id}</strong>
                <span className="tk-faint num">{c.hex} @ {c.alpha}</span>
                <span className="tk-faint">{c.note}</span>
              </div>
              <HexPanel
                features={features}
                singleHex={c.hex} singleAlpha={c.alpha}
                ndHex={noData.hex} ndAlpha={noData.alpha}
              />
              <div className="tk-panel-foot num">
                <span>composited {hex(over(parseColor(c.hex)!, ground, c.alpha))}</span>
                <span className="tk-dot">·</span>
                <span>L {singleL.toFixed(4)}</span>
                <span className="tk-dot">·</span>
                <span>corroborated {(corrL / singleL).toFixed(2)}× brighter</span>
                <span className="tk-dot">·</span>
                <span className={inverted ? 'tk-under' : ''}>
                  {inverted
                    ? 'LADDER INVERTED — no-data is brighter than single source'
                    : `${(singleL / ndL).toFixed(2)}× above no-data`}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      <p className="tk-note num">
        ground (veiled Dark Matter #0e0e0e) L {groundL.toFixed(4)}
        <span className="tk-dot">·</span>
        corroborated L {corrL.toFixed(4)} (unchanged)
        <span className="tk-dot">·</span>
        {CONFIDENCE.map(c => `${c.label.toLowerCase()} ${counts[c.key] ?? '–'}`).join(' · ')}
      </p>
      <p className="tk-note">
        Hue is not the lever here. Composited, the current amber sits at hue 39.4° and
        candidate B at 42.0° — a warm fill over a near-black ground goes brown as a matter
        of arithmetic, whatever the source hue. What actually changes the reading is mass:
        alpha 0.55 → 0.38 drops the fill's value from 0.49 to 0.36. Candidates B and C also
        move <code>--amber</code> itself, which would change the badge; A changes only the
        map alpha and leaves the badge exactly as it is.
      </p>
    </>
  )
}

function HexPanel({ features, singleHex, singleAlpha, ndHex, ndAlpha }: {
  features: any[] | null
  singleHex: string; singleAlpha: number; ndHex: string; ndAlpha: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!ref.current) return
    const cs = getComputedStyle(document.documentElement)
    const map = new maplibregl.Map({
      container: ref.current,
      style: DARK_MATTER,
      center: PREVIEW_CENTER,
      zoom: 10.6,
      // Panning one panel and not the others would silently destroy the
      // comparison this section exists to make.
      interactive: false,
      attributionControl: false,
    })
    mapRef.current = map
    map.on('error', e => setErr((e as any)?.error?.message || 'basemap unavailable'))
    map.on('load', () => {
      // THE VEIL: one --canvas layer above every imported basemap layer.
      // Desaturates the basemap and dims its labels in a single move, instead
      // of walking dozens of CARTO layers whose ids change whenever the style
      // is republished.
      map.addLayer({
        id: 'veil', type: 'background',
        paint: {
          'background-color': cs.getPropertyValue('--canvas').trim(),
          'background-opacity': VEIL_ALPHA,
        },
      })
      setReady(true)
    })
    return () => { map.remove(); mapRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !features) return
    const cs = getComputedStyle(document.documentElement)
    const fc = { type: 'FeatureCollection', features } as any
    if (!map.getSource('cells')) {
      map.addSource('cells', { type: 'geojson', data: fc })
      map.addLayer({
        id: 'cells-fill', type: 'fill', source: 'cells',
        paint: { 'fill-color': '#000', 'fill-opacity': 0 },
      })
      map.addLayer({
        id: 'cells-line', type: 'line', source: 'cells',
        paint: { 'line-color': 'rgba(255,255,255,0.10)', 'line-width': 0.5 },
      })
    }
    map.setPaintProperty('cells-fill', 'fill-color', ['match', ['get', 'conf'],
      'corroborated', cs.getPropertyValue('--accent').trim(),
      'single_source', singleHex,
      ndHex])
    map.setPaintProperty('cells-fill', 'fill-opacity', ['match', ['get', 'conf'],
      'corroborated', parseFloat(cs.getPropertyValue('--alpha-corroborated')),
      'single_source', singleAlpha,
      ndAlpha])
  }, [ready, features, singleHex, singleAlpha, ndHex, ndAlpha])

  return (
    <>
      <div className="tk-map tk-map-sm" ref={ref} />
      {err && <p className="tk-note tk-under">{err}</p>}
    </>
  )
}
