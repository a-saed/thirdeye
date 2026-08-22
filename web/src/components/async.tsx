/*
 * FETCH STATE, IN ONE PLACE.
 *
 * Every component here talks to an API that is currently on localhost with the
 * whole store in RAM, so everything returns in milliseconds — which is exactly
 * why the loading and failure paths were never written, and exactly why they
 * would appear first in production, on a phone, or once the API is remote.
 *
 * THE RULE THAT MATTERS MOST: a failed fetch and a real zero must never look
 * the same. Rendering 0, an empty chart or an empty table on failure is the
 * same lie as rendering 0 for a missing metric — the one thing this product
 * exists not to do. So `empty` is a state the caller declares deliberately,
 * and it is never inferred from an error.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import './async.css'

/** Every request is bounded. Without a timeout a hung socket leaves a skeleton
 *  on screen for ever, which reads as "still working" rather than "broken" —
 *  the same failure that once left a pipeline run wedged at 3 KB/s for two
 *  hours. Stated, not guessed at. */
export const FETCH_TIMEOUT_MS = 12_000

export type Async<T> =
  | { s: 'idle' }
  | { s: 'loading' }
  | { s: 'ok'; data: T }
  | { s: 'error'; message: string }

export interface UseFetch<T> {
  state: Async<T>
  retry: () => void
}

/**
 * Fetch JSON with a timeout, cancellation and a retry handle.
 *
 * @param url    request URL, or null to stay idle (a slot with no location
 *               chosen is idle, not loading and not empty)
 * @param label  what this is, used in the error message — "Could not load the
 *               records" beats "something went wrong", which tells a user
 *               nothing and gives them nothing to do
 */
export function useFetch<T>(url: string | null, label: string): UseFetch<T> {
  const [state, setState] = useState<Async<T>>({ s: 'idle' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => setNonce(n => n + 1), [])

  useEffect(() => {
    if (!url) { setState({ s: 'idle' }); return }
    let cancelled = false
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
    setState({ s: 'loading' })

    fetch(url, { signal: ctrl.signal })
      .then(async r => {
        if (!r.ok) {
          const body = (await r.text()).slice(0, 200)
          // The API returns {"error": "..."} — surface its reason, not a code.
          let reason = body
          try { reason = JSON.parse(body).error ?? body } catch { /* plain text */ }
          throw new Error(reason || `HTTP ${r.status}`)
        }
        return r.json() as Promise<T>
      })
      .then(data => { if (!cancelled) setState({ s: 'ok', data }) })
      .catch(err => {
        if (cancelled) return
        const message = err?.name === 'AbortError'
          ? `${label} timed out after ${FETCH_TIMEOUT_MS / 1000}s.`
          : `${label} failed: ${err?.message ?? 'network unreachable'}.`
        setState({ s: 'error', message })
      })
      .finally(() => clearTimeout(timer))

    return () => { cancelled = true; clearTimeout(timer); ctrl.abort() }
  }, [url, label, nonce])

  return { state, retry }
}

/** Skeletons appear only if the wait is long enough to notice. Below this a
 *  skeleton is a flash of grey that reads as a glitch. */
const SKELETON_DELAY_MS = 150

export function useDelayed(active: boolean, ms = SKELETON_DELAY_MS) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    if (!active) { setShow(false); return }
    const t = setTimeout(() => setShow(true), ms)
    return () => clearTimeout(t)
  }, [active, ms])
  return show
}

/** A skeleton block. Sized by the caller to match the real content, so nothing
 *  moves when data lands — a spinner that is then replaced by a table is two
 *  layouts, and the second one jumps. */
export function Skel({ w, h, r, className }: {
  w?: number | string; h?: number | string; r?: number; className?: string
}) {
  return (
    <span
      className={'sk' + (className ? ' ' + className : '')}
      style={{ width: w, height: h, borderRadius: r }}
      aria-hidden="true"
    />
  )
}

/** Failure, said plainly, with the one action that might fix it. */
export function ErrorBox({ message, onRetry, compact }: {
  message: string; onRetry?: () => void; compact?: boolean
}) {
  return (
    <div className={'as-err' + (compact ? ' as-err-compact' : '')} role="alert">
      <span>{message}</span>
      {onRetry && (
        <button className="as-retry" onClick={onRetry}>Try again</button>
      )}
    </div>
  )
}

/** Nothing there, and that is a real answer rather than a failure. */
export function EmptyBox({ children }: { children: React.ReactNode }) {
  return <p className="as-empty">{children}</p>
}

/** Convenience wrapper: idle / loading / error / ok, with the empty case left
 *  to the caller because only the caller knows what empty means for its data. */
export function AsyncBlock<T>({ state, retry, skeleton, idle, children }: {
  state: Async<T>
  retry?: () => void
  skeleton: React.ReactNode
  idle?: React.ReactNode
  children: (data: T) => React.ReactNode
}) {
  const showSkel = useDelayed(state.s === 'loading')
  if (state.s === 'idle') return <>{idle ?? null}</>
  if (state.s === 'loading') return <>{showSkel ? skeleton : null}</>
  if (state.s === 'error') return <ErrorBox message={state.message} onRetry={retry} />
  return <>{children(state.data)}</>
}
