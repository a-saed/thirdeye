/* Shared thresholds, imported from config/thresholds.json at build time.
 *
 * The same file the Python pipeline and the Go API read. MIN_PCT_BASE and
 * DEFAULT_K each existed twice in this codebase — once in report.tsx and once
 * in compare.tsx — which is two places for one rule to drift.
 *
 * SEMANTIC rules are NOT here. Direction of good, weakest-link ordering and
 * saturation classification are applied in Go and carried on the response;
 * this file holds only presentation-side numbers the API cannot send.
 */
import cfg from '../../../config/thresholds.json'

export const REPORT_RES = cfg.resolutions.report
export const COVERAGE_RES = cfg.resolutions.coverage
export const DEFAULT_K = cfg.catchment.default_k
export const MAX_K = cfg.catchment.max_k
/** Below this base, show counts rather than a percentage: "3 to 1" beats
 *  "-66.7%", which dresses a difference of two records as a finding. */
export const MIN_PCT_BASE = cfg.percentages.min_base
