/* Presentation helpers. One definition each; fmt, cap and shortCategory were
 * all written twice. */

/** Missing is "—", never 0. The single easiest place for a UI to lie. */
export const fmt = (v: number | null | undefined, digits = 0) =>
  v == null || Number.isNaN(v)
    ? '—'
    : v.toLocaleString(undefined, {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
      })

/** Sentence case at the render boundary, so category values stay lowercase in
 *  data and in query strings. */
export const cap = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t)

/** Source categories are not written for readers: Foursquare ships a full path
 *  ("Dining and Drinking > Cafe, Coffee, and Tea House > Coffee Shop"),
 *  Overture ships snake_case. Show the leaf; keep the original in a tooltip,
 *  because the raw value is provenance. */
export function shortCategory(raw: string): string {
  if (!raw) return '—'
  const leaf = raw.split('>').pop()!.trim()
  return cap(leaf.replace(/_/g, ' ').toLowerCase())
}

/** Metres between two points. Equirectangular is plenty at the ~200 m scale
 *  this is used for. */
export function metres(
  a: { lat: number; lon: number }, b: { lat: number; lon: number },
) {
  const dy = (a.lat - b.lat) * 111320
  const dx = (a.lon - b.lon) * 111320 * Math.cos((a.lat * Math.PI) / 180)
  return Math.hypot(dx, dy)
}
