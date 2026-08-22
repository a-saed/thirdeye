import React, { useState } from 'react'
import './CopyLink.css'

/** Copy the current URL.
 *
 *  The URL is the share format: every control on these screens writes its
 *  state into the query string, so a pasted link reproduces the exact view
 *  rather than dropping the recipient on a default. That only holds if the
 *  address bar is genuinely current — see the syncUrl effects on each route.
 */
export default function CopyLink({ label = 'Copy link' }: { label?: string }) {
  const [done, setDone] = useState(false)

  const copy = async () => {
    const url = window.location.href
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // Clipboard API needs a secure context and permission. Fall back rather
      // than failing silently, so the link is still obtainable.
      const el = document.createElement('textarea')
      el.value = url
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      el.remove()
    }
    setDone(true)
    setTimeout(() => setDone(false), 1600)
  }

  return (
    <button className={'cl' + (done ? ' cl-done' : '')} onClick={copy} title={window.location.href}>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        {done
          ? <path d="M3 8.5 L6.5 12 L13 4.5" />
          : <>
              <rect x="5.5" y="5.5" width="8" height="8" rx="1.6" />
              <path d="M10.5 5.5 V3.6 A1.1 1.1 0 0 0 9.4 2.5 H3.6 A1.1 1.1 0 0 0 2.5 3.6 V9.4 A1.1 1.1 0 0 0 3.6 10.5 H5.5" />
            </>}
      </svg>
      {done ? 'Copied' : label}
    </button>
  )
}
