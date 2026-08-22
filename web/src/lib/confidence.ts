/* Confidence presentation — ONE definition, previously three.
 *
 * The labels and glyphs lived in report.tsx, compare.tsx and home.tsx: three
 * copies of the words a user reads for how much to trust a number.
 *
 * The ORDERING is not here. Which confidence is weaker is a rule, and rules
 * live in Go — the API sends `confidence_rank` and this module never re-derives
 * it. What is here is only how the three states are shown.
 *
 * The glyph is a REDUNDANT CHANNEL (DESIGN.md §3): confidence must survive a
 * greyscale screenshot, a projector and colour-vision deficiency. It must also
 * survive a screen reader, which is why every use pairs it with a text label
 * rather than leaving a bare ● in a span.
 */
import type { Conf } from './types'

export const CONF_LABEL: Record<Conf, string> = {
  corroborated: 'Corroborated',
  single_source: 'Single source',
  unavailable: 'No data',
}

export const CONF_GLYPH: Record<Conf, string> = {
  corroborated: '●',
  single_source: '○',
  unavailable: '–',
}

/** What each state actually means, for tooltips and assistive text. */
export const CONF_MEANING: Record<Conf, string> = {
  corroborated:
    'Two sources cover every cell in this catchment and their counts agree within tolerance.',
  single_source:
    'At least one cell rests on a single source. A catchment takes the weakest confidence among its cells — averaging would launder the uncertainty.',
  unavailable:
    'No source covers this metric here. Not a count of zero.',
}
