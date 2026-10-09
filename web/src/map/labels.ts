import type maplibregl from 'maplibre-gl'

/** Id of the basemap's first label layer, to pass as addLayer's beforeId.
 *
 * Layers stack in the order they are added, so anything added after the
 * basemap paints over its place names. Area layers (the veil, hex fills and
 * outlines) go beneath the labels so the names stay readable through the
 * grid; point layers are the content and stay on top. Undefined when the
 * style has no labels, which addLayer treats as "on top". */
export function labelsBelow(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers.find(l => l.type === 'symbol')?.id
}
