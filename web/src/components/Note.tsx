import React, { useId, useState } from 'react'
import './Note.css'

/** An explanation that survives having no pointer.
 *
 *  TOUCH HAS NO HOVER, AND THIS PRODUCT PUTS CAVEATS IN TOOLTIPS.
 *  Measured on a phone: /report carried ten distinct pieces of meaning whose
 *  only carrier was a `title` attribute — the confidence badge's explanation,
 *  the res-8 population caveat, the duplicate tag, the snapshot gap. A phone
 *  user got every number and none of the qualifications on it. On a product
 *  whose rule is that provenance is not optional, that is a correctness bug
 *  wearing a UI costume.
 *
 *  The note opens IN FLOW rather than as an overlay: it pushes the content
 *  below it down. That costs a reflow and buys no positioning logic, no
 *  collision handling against the viewport edge, and no z-index argument with
 *  a full-screen map — three things a floating popover would have to solve on
 *  the smallest screen, which is exactly where they are hardest.
 *
 *  `title` is kept on the trigger, so a mouse user still gets the native
 *  tooltip and desktop behaviour is unchanged.
 */
export default function Note({ children, label = 'Why this figure is qualified' }: {
  children: React.ReactNode
  /** Accessible name for the trigger. Say what the note is about. */
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const id = useId()

  return (
    <>
      <button
        type="button"
        className={'nt-trigger' + (open ? ' nt-on' : '')}
        aria-expanded={open}
        aria-controls={id}
        aria-label={label}
        title={label}
        onClick={() => setOpen(o => !o)}
      >
        {/* Not an emoji: emoji render at the mercy of the platform font and
            this one has to sit on a 12px baseline next to a number. */}
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.5" />
          <path d="M8 7.2v4" />
          <circle cx="8" cy="4.8" r="0.9" className="nt-dot" />
        </svg>
      </button>
      {open && (
        <span className="nt-body" id={id} role="note">
          {children}
        </span>
      )}
    </>
  )
}
