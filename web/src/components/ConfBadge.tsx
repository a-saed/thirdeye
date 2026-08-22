import React from 'react'
import type { Conf } from '../lib/types'
import { CONF_LABEL, CONF_GLYPH, CONF_MEANING } from '../lib/confidence'
import './ConfBadge.css'

/** The confidence badge, previously written three times with three class
 *  prefixes.
 *
 *  single_source gets NO warning styling: 66% of inhabited cells are
 *  single-source, and if the normal state looks like an error the product
 *  looks broken everywhere it works.
 *
 *  The glyph is decorative to assistive tech (aria-hidden) because the label
 *  beside it already carries the meaning in words — a screen reader announcing
 *  "black circle Corroborated" is noise, but a bare ● with no label would be
 *  silence. Redundant encoding has to reach non-sighted users too.
 */
export default function ConfBadge({ c, size = 'md' }: { c: Conf; size?: 'md' | 'sm' }) {
  return (
    <span className={`cb cb-${c} cb-${size}`} title={CONF_MEANING[c]}>
      <span className="cb-glyph" aria-hidden="true">{CONF_GLYPH[c]}</span>
      {CONF_LABEL[c]}
    </span>
  )
}

/** Glyph only, for dense contexts such as a comparison row. Carries its label
 *  as screen-reader-only text rather than relying on colour and shape. */
export function ConfDot({ c }: { c: Conf }) {
  return (
    <span className={`cb-dot cb-${c}`} title={CONF_MEANING[c]}>
      <span aria-hidden="true">{CONF_GLYPH[c]}</span>
      <span className="sr-only">{CONF_LABEL[c]}</span>
    </span>
  )
}
