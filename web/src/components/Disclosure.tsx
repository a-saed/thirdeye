import React, { useId, useState } from 'react'
import './Disclosure.css'

/** A section that collapses on a phone and does not on a desktop.
 *
 *  THE SUMMARY MUST SAY WHAT IT IS HIDING.
 *  `count` is not decoration. A collapsed section labelled "Show more" is how
 *  a caveat gets lost — the reader has no way to tell whether the fold hides
 *  four qualifications or none, so the honest default becomes "expand
 *  everything", which is the same as not collapsing at all. "Caveats · 4"
 *  lets someone decide without opening it.
 *
 *  Open/closed is CSS-driven, not JS-driven: the body renders always and the
 *  media query decides whether the toggle exists. That keeps desktop
 *  identical to what it was, keeps the content in the DOM for find-in-page
 *  and for a screen reader, and means no viewport listener has to agree with
 *  a stylesheet about where the breakpoint is.
 */
export default function Disclosure({ summary, count, children, defaultOpen = false }: {
  /** What the section is. Sentence case, no trailing punctuation. */
  summary: string
  /** How much is inside. Omit only when there is genuinely nothing to count. */
  count?: React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()

  return (
    <section className="dc">
      <button
        type="button"
        className="dc-summary"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(o => !o)}
      >
        <span className="dc-label">
          {summary}
          {count != null && <span className="dc-count">{count}</span>}
        </span>
        <span className="dc-caret" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      <div className="dc-body" id={id} data-open={open ? 'true' : 'false'}>
        {children}
      </div>
    </section>
  )
}
