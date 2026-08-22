/* Fails the build on an invalid paint expression.
 *
 * Every expression here is IMPORTED from src/map/paint.mjs, never retyped, so
 * this cannot validate something the app does not actually render.
 */
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec'
import {
  coverageFillColor, coverageFillOpacity, coverageLinePaint, catchmentFillOpacity,
} from '../src/map/paint.mjs'

// Stand-in token values; only the SHAPE of the expression is under test.
const t = {
  accent: '#45C9A5', amber: '#D8A33F', noData: '#3F4A52',
  alphaCorroborated: 0.85, alphaSingle: 0.38, alphaNoData: 0.58,
}

const style = {
  version: 8,
  sources: { cells: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } } },
  layers: [
    { id: 'veil', type: 'background', paint: { 'background-color': '#101315', 'background-opacity': 0.45 } },
    { id: 'cells-fill', type: 'fill', source: 'cells',
      paint: { 'fill-color': coverageFillColor(t), 'fill-opacity': coverageFillOpacity(t) } },
    { id: 'cells-line', type: 'line', source: 'cells', paint: coverageLinePaint() },
    { id: 'catchment-fill', type: 'fill', source: 'cells',
      paint: { 'fill-color': t.accent, 'fill-opacity': catchmentFillOpacity() } },
  ],
}

const errs = validateStyleMin(style)
if (errs.length) {
  console.error('INVALID map style:')
  for (const e of errs) console.error('  ' + e.message)
  process.exit(1)
}
console.log(`map style valid — ${style.layers.length} layers checked`)
