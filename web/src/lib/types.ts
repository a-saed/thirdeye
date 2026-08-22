/* API response types — ONE definition, not one per route.
 *
 * report.tsx and compare.tsx each carried their own Metric and Report
 * interfaces, and compare's was a subset. They had already diverged: compare
 * was missing `k_ring` and the build broke when a component needed it. A type
 * that describes someone else's response should be written once.
 */

export type Conf = 'corroborated' | 'single_source' | 'unavailable'

export interface Metric {
  metric: string
  value: number
  value_per_land_km2: number | null
  value_per_land_km2_unavailable_reason?: string
  track: string
  confidence: Conf
  /** Weakest-link ORDERING as a number, from the API. Never re-derived here. */
  confidence_rank: number
  contributing_sources: string[]
  source_counts?: Record<string, number>
  as_of: string
  source_snapshots: Record<string, string>
  agreement_ratio: number | null
  stale: boolean
  cells_by_confidence: Record<string, number>
  cells_total: number
  cells_no_data: number
  cells_none_present: number
  native_res: number
  /** "higher" | "lower" | "context", decided in Go and rendered here. */
  direction_of_good: string
}

export interface CatchmentCell {
  h3: string
  confidence: Conf
  business_count: number
  land_fraction: number
  in_coverage: boolean
}

export interface Point {
  as_of: string
  snapshot_id: string
  value: number
  confidence: Conf
  status: 'ok' | 'artifact_suspected' | 'gap'
}

export interface Series {
  metric: string
  track: string
  series_raw: Point[]
  series_corrected: Point[] | null
  excluded_from_corrected: {
    snapshot_id: string; as_of: string; value: number; reason: string
  }[]
  correction_status: 'not_needed' | 'applied' | 'withheld_too_short'
  series_corrected_unavailable_reason?: string
  artifact_suspected_count: number
  member_cells_with_artifacts: number
  member_cells_total: number
  divergence_note?: string
  growth_pct_raw: number | null
  growth_pct_corrected: number | null
  gap_note?: string
  series_sources: string[]
  comparable_to_latest_metric: boolean
  scope_note?: string
}

export interface Limitations {
  duplicate_inflation_pct_range: [number, number]
  position_error_median_m: number
  position_error_p90_m: number
  position_error_max_m: number
  independence_caveat: string
  notes?: string[]
}

export interface Report {
  query: {
    lat: number; lon: number; radius_m: number; category: string; k_ring: number
  }
  context: {
    land_area_km2: number
    raw_area_km2: number
    nominal_area_km2: number
    land_fraction_mean: number
    saturation_class: string
    saturation_cells: Record<string, number>
    builtup_pct: number
    builtup_growth_pct: number
    /** The growth threshold applied in Go, so no client compares to a number. */
    growth_is_material: boolean
    coverage_ratio: number | null
    density_distorted: boolean
    cell_count: number
    h3_res: number
    k_ring: number
    cells: CatchmentCell[]
  }
  metrics: Metric[]
  time_series: Series[]
  limitations: Limitations
}

export interface PlaceRec {
  name: string
  source: string
  category: string
  groups?: string
  lat: number
  lon: number
  distance_m: number
  duplicate_suspected: boolean
  same_point: number
  snapshot: string
}

export interface PlacesResp {
  total: number
  total_unfiltered: number
  returned: number
  offset: number
  duplicate_flagged: number
  places: PlaceRec[]
  note: string
}

export interface Coverage {
  in_coverage: boolean
  confidence?: Conf
  businesses?: number
  governorate?: string
}

export interface PlaceLabel {
  name: string
  detail: string
  kind?: string
  source?: string
  lat: number
  lon: number
  attribution: string
}
