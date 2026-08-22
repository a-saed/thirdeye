import React, { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

// COVERAGE MAP — the first screen, deliberately.
//
// It renders entirely from a static GeoJSON (res-8, 9,938 hexes, ~0.6 MB
// gzipped) and never calls the API. The point is to show what data exists
// BEFORE anyone picks a location, rather than letting them choose a spot and
// then telling them the evidence is thin.
//
// Colour encodes the BUSINESS track only — the layer the study found weakest.
// 'unavailable' is not 'zero businesses'; it means no source covers business
// data in that cell at all, and it is by far the largest class.
//
// TWO DENOMINATORS, ALWAYS BOTH.
// The operational polygon includes a 2 km dilation ring and a long tail of
// Nile-valley farmland, so 'coverage over the polygon' understates the
// product: those cells have no business data because they have no businesses.
// The legend shows the full polygon AND inhabited cells only (population >=100
// and >=5% built-up) side by side, because neither number is honest alone —
// the first flatters the desert into a failure, the second quietly narrows the
// area being claimed. Uninhabited cells render faded and can be hidden.

const COLORS = {
  corroborated: '#2b6b5c',   // muted teal — two sources agree within tolerance
  single_source: '#c9a227',  // muted amber — one source only
  unavailable: '#b8b8b2',    // grey — no business data at all
}

const LABELS = {
  corroborated: 'Corroborated',
  single_source: 'Single source',
  unavailable: 'No business data',
}

// Restrained basemap. Positron is greyscale and keyless, so the hex ramp is
// the only thing carrying colour.
const BASEMAP = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

// Fallback if the basemap host is unreachable: a plain background. The data
// still renders — the map must not be blank just because tiles failed.
const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#f2f2ef' } }],
}

export default function CoverageMap() {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const [summary, setSummary] = useState(null)
  const [hidden, setHidden] = useState({})
  const [inhabitedOnly, setInhabitedOnly] = useState(false)
  const [tip, setTip] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/coverage-summary.json').then(r => r.json()).then(setSummary).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    async function init() {
      let style = BASEMAP
      try {
        const probe = await fetch(BASEMAP, { method: 'GET' })
        if (!probe.ok) style = FALLBACK_STYLE
      } catch {
        style = FALLBACK_STYLE
      }
      if (cancelled) return

      const map = new maplibregl.Map({
        container: ref.current,
        style,
        center: [31.05, 30.15],   // between Cairo and Alexandria
        zoom: 7.6,
        attributionControl: false,
      })
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

      // A thrown addLayer leaves an empty map that looks like "no data" rather
      // than "broken code". Surface it instead of only logging it.
      map.on('error', e => setError(e?.error?.message || String(e?.error || e)))

      map.on('load', async () => {
       try {
        const res = await fetch('/coverage-res8.geojson')
        if (!res.ok) throw new Error(`coverage-res8.geojson: HTTP ${res.status}`)
        const data = await res.json()
        if (cancelled) return
        map.addSource('cells', { type: 'geojson', data })

        map.addLayer({
          id: 'cells-fill',
          type: 'fill',
          source: 'cells',
          paint: {
            'fill-color': [
              'match', ['get', 'conf'],
              'corroborated', COLORS.corroborated,
              'single_source', COLORS.single_source,
              COLORS.unavailable,
            ],
            // Slightly translucent so the basemap gives geographic context
            // without the fill turning muddy. Uninhabited cells are faded
            // rather than removed: they ARE in the coverage area, they just
            // should not read as equal weight to the served city.
            //
            // NESTING ORDER MATTERS: 'zoom' may only feed a TOP-LEVEL step or
            // interpolate. Wrapping the interpolate in a 'case' makes the whole
            // paint property invalid, and MapLibre rejects the entire addLayer
            // call - the map goes blank rather than degrading. So interpolate
            // is outermost and the per-feature 'case' sits in each stop output.
            'fill-opacity': [
              'interpolate', ['linear'], ['zoom'],
              7, ['case', ['==', ['get', 'inh'], 1], 0.55, 0.20],
              11, ['case', ['==', ['get', 'inh'], 1], 0.72, 0.26],
            ],
          },
        })
        // Hairline borders only above z9 — at city scale 9,938 outlines is
        // visual noise that competes with the fill.
        map.addLayer({
          id: 'cells-line',
          type: 'line',
          source: 'cells',
          paint: {
            'line-color': 'rgba(0,0,0,.18)',
            'line-width': 0.4,
            'line-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 10.5, 1],
          },
        })
        map.addLayer({
          id: 'cells-hover',
          type: 'line',
          source: 'cells',
          paint: { 'line-color': '#1a1a1a', 'line-width': 1.6 },
          filter: ['==', ['get', 'h3'], ''],
        })

        map.on('mousemove', 'cells-fill', e => {
          const f = e.features?.[0]
          if (!f) return
          map.getCanvas().style.cursor = 'crosshair'
          map.setFilter('cells-hover', ['==', ['get', 'h3'], f.properties.h3])
          setTip({ x: e.point.x, y: e.point.y, p: f.properties })
        })
        map.on('mouseleave', 'cells-fill', () => {
          map.getCanvas().style.cursor = ''
          map.setFilter('cells-hover', ['==', ['get', 'h3'], ''])
          setTip(null)
        })

        setLoading(false)
       } catch (err) {
        setError(err.message)
        setLoading(false)
       }
      })
    }
    init()
    return () => { cancelled = true; mapRef.current?.remove() }
  }, [])

  // Legend toggles filter the layer rather than recolouring, so hiding the
  // dominant class reveals what is underneath it.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.getLayer('cells-fill')) return
    const off = Object.keys(hidden).filter(k => hidden[k])
    const clauses = []
    if (off.length) clauses.push(['!', ['in', ['get', 'conf'], ['literal', off]]])
    if (inhabitedOnly) clauses.push(['==', ['get', 'inh'], 1])
    const filter = clauses.length ? ['all', ...clauses] : null
    map.setFilter('cells-fill', filter)
    map.setFilter('cells-line', filter)
  }, [hidden, inhabitedOnly])

  const all = summary?.all_cells
  const inh = summary?.inhabited
  const byGov = summary?.inhabited_by_governorate
  // Always one decimal. JSON round-trips 66.0 as 66, which broke the column
  // alignment and made a rounded figure look more precise than its neighbours.
  const f = v => (v == null ? '—' : `${v.toFixed(1)}%`)

  return (
    <>
      <div id="map" ref={ref} />
      {loading && <div className="loading">loading 9,938 cells…</div>}
      {error && <div className="err"><strong>Layer failed to render.</strong> {error}</div>}

      <div className="panel">
        <h1>Business-data coverage</h1>
        <p className="sub">H3 res-8 · Cairo · Giza · Qalyubiya · Alexandria</p>

        <div className="legend">
          <div className="head">
            <span className="lab" />
            <span className="pct">all cells</span>
            <span className="pct">inhabited</span>
          </div>
          {['corroborated', 'single_source', 'unavailable'].map(k => (
            <div
              key={k}
              className={'row' + (hidden[k] ? ' off' : '')}
              onClick={() => setHidden(h => ({ ...h, [k]: !h[k] }))}
              title="click to hide/show"
            >
              <span className="sw" style={{ background: COLORS[k] }} />
              <span className="lab">{LABELS[k]}</span>
              <span className="pct dim">{f(all?.pct?.[k])}</span>
              <span className="pct">{f(inh?.pct?.[k])}</span>
            </div>
          ))}
          <div className="head foot">
            <span className="lab">cells</span>
            <span className="pct dim">{all?.cells?.toLocaleString() ?? '—'}</span>
            <span className="pct">{inh?.cells?.toLocaleString() ?? '—'}</span>
          </div>
        </div>

        <label className="toggle">
          <input
            type="checkbox"
            checked={inhabitedOnly}
            onChange={e => setInhabitedOnly(e.target.checked)}
          />
          Hide uninhabited cells
        </label>

        <div className="note">
          Over the full operational polygon,{' '}
          <strong>{f(all?.pct?.unavailable)}</strong> has no business data — but that
          polygon is four governorates plus a 2 km ring, so it counts desert and
          Delta farmland as coverage failures. Over{' '}
          <strong>inhabited cells only</strong> (≥100 people and ≥5% built-up,{' '}
          {inh?.cells?.toLocaleString() ?? '—'} of {all?.cells?.toLocaleString() ?? '—'}),
          it is <strong>{f(inh?.pct?.unavailable)}</strong> with no data,{' '}
          <strong>{f(inh?.pct?.single_source)}</strong> on one source, and{' '}
          <strong>{f(inh?.pct?.corroborated)}</strong> corroborated.
          <br /><br />
          “No business data” is not “no businesses” — it means no source covers
          that cell.
        </div>

        {byGov && (
          <div className="gov">
            <div className="gov-h">Inhabited cells, by governorate</div>
            <table>
              <thead>
                <tr>
                  <th /><th>cells</th><th>corrob.</th><th>single</th><th>none</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byGov)
                  .sort((a, b) => a[1].pct.unavailable - b[1].pct.unavailable)
                  .map(([g, s]) => (
                    <tr key={g}>
                      <td>{g}</td>
                      <td className="num dim">{s.cells.toLocaleString()}</td>
                      <td className="num">{f(s.pct.corroborated)}</td>
                      <td className="num">{f(s.pct.single_source)}</td>
                      <td className="num">{f(s.pct.unavailable)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="hint">Click a legend row to hide that class.</div>
      </div>

      {tip && (
        <div className="tip" style={{ left: tip.x, top: tip.y }}>
          <div><span className="k">confidence</span> {LABELS[tip.p.conf]}</div>
          <div><span className="k">businesses</span> {tip.p.n}</div>
          <div><span className="k">governorate</span> {tip.p.gov}</div>
          <div><span className="k">population</span> {tip.p.pop?.toLocaleString()}</div>
          <div><span className="k">built-up</span> {tip.p.bu}%</div>
          <div><span className="k">saturation</span> {tip.p.sat}</div>
          <div><span className="k">land fraction</span> {tip.p.land}</div>
          <div className={tip.p.inh ? 'inh' : 'uninh'}>
            {tip.p.inh ? 'inhabited' : 'uninhabited — excluded from the served denominator'}
          </div>
        </div>
      )}
    </>
  )
}
