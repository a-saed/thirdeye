/*
 * MAP CONTROLS — zoom in / zoom out / locate me.
 *
 * Spec: docs/DESIGN.md. Tokens: src/tokens.css.
 *
 * Custom markup rather than maplibregl.NavigationControl, because MapLibre's
 * controls carry their icons as background-image data URIs with the colours
 * baked in. Restyling those means either filter hacks or re-declaring the
 * images, and neither survives a MapLibre upgrade. Owning the markup is less
 * code than fighting it, and the buttons then use the same tokens as every
 * other control in the product.
 *
 * The geolocation itself lives in useLocate, shared with the home panel's
 * "Use my location" button.
 */
import React from 'react'
import type maplibregl from 'maplibre-gl'
import { useLocate, type Located } from './useLocate'

export type { Located }

export default function MapControls({ map, onLocate }: {
  map: maplibregl.Map | null
  /** Omit to hide the locate button — e.g. on a map that is not a picker. */
  onLocate?: (l: Located) => void
}) {
  const { status, locate, message } = useLocate(onLocate)

  return (
    <div className="mc">
      <div className="mc-group">
        <button
          className="mc-btn" title="Zoom in" aria-label="Zoom in"
          onClick={() => map?.zoomIn()}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 3.5v9M3.5 8h9" />
          </svg>
        </button>
        <button
          className="mc-btn" title="Zoom out" aria-label="Zoom out"
          onClick={() => map?.zoomOut()}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3.5 8h9" />
          </svg>
        </button>
      </div>

      {onLocate && (
        <div className="mc-group">
          <button
            className={'mc-btn' + (status === 'locating' ? ' mc-btn-active' : '')}
            title="Use my location" aria-label="Use my location"
            onClick={locate} disabled={status === 'locating'}
          >
            {/* Crosshair, not a pin: it marks where you are, not a place we
                have data about. */}
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="8" cy="8" r="3.2" />
              <path d="M8 1v2.2M8 12.8V15M1 8h2.2M12.8 8H15" />
            </svg>
          </button>
        </div>
      )}

      {message && <div className="mc-msg">{message}</div>}
    </div>
  )
}
