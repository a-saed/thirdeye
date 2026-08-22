/* Map paint expressions, in ONE place.
 *
 * Shared by the components that render them and by scripts/validate-style.mjs,
 * which runs them through the MapLibre style spec. A copy of an expression in
 * a test drifts from the copy in the component and then validates the wrong
 * thing, so there is exactly one definition and both sides import it.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE (DESIGN.md §6): `zoom` may only be the
 * input to a TOP-LEVEL `step` or `interpolate`. Nest one inside `*`, `case` or
 * `match` and the whole paint property is invalid — MapLibre then rejects the
 * entire addLayer call and the map renders with NO data layer at all, which
 * looks like missing data rather than broken code. It has shipped that way
 * twice.
 */

/** Confidence colour ramp for the coverage hexes. */
export function coverageFillColor(t) {
  return ['match', ['get', 'conf'],
    'corroborated', t.accent,
    'single_source', t.amber,
    t.noData]
}

/** Per-feature opacity at one zoom stop: confidence ladder x uninhabited fade
 *  x the zoom factor. Every class takes the same factor, so the measured
 *  luminance ladder survives the fade. */
function ladder(t, factor) {
  return ['*',
    ['match', ['get', 'conf'],
      'corroborated', t.alphaCorroborated,
      'single_source', t.alphaSingle,
      t.alphaNoData],
    ['case', ['==', ['get', 'inh'], 1], 1, 0.35],
    factor]
}

/** res-8 hexes are 0.74 km2: past z12 a single cell fills the screen and buries
 *  the streets the user is reading. Fade with zoom — interpolate OUTERMOST. */
export function coverageFillOpacity(t) {
  return ['interpolate', ['linear'], ['zoom'],
    11, ladder(t, 1),
    13, ladder(t, 0.55),
    15, ladder(t, 0.28)]
}

/** Hairline cell borders, only once the cells are small enough to read. */
export function coverageLinePaint() {
  return {
    'line-color': 'rgba(255,255,255,0.10)',
    'line-width': 0.4,
    'line-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 10.5, 1],
  }
}

/** The catchment ring on the report map: origin cell brighter than the rest. */
export function catchmentFillOpacity() {
  return ['case', ['==', ['get', 'origin'], 1], 0.30, 0.14]
}
