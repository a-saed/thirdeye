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
 * ACCURACY IS TREATED AS DATA, NOT AS A DETAIL.
 * Browser geolocation returns a coordinate AND an accuracy radius, and that
 * radius is frequently hundreds of metres — on a desktop with no GPS it is
 * often kilometres, because it is derived from IP or wifi. This product
 * refuses to report a 500 m catchment around a point known only to ±3 km:
 * that is the same error as treating a block-level position as an address.
 * The accuracy is surfaced, and the caller decides what to do with it.
 */
import React, { useState } from 'react'
import type maplibregl from 'maplibre-gl'

export interface Located {
  lat: number
  lon: number
  /** Radius in metres the browser claims the position is good to. */
  accuracyM: number
  /** Everything the browser reported, untransformed, for diagnosis. */
  raw: {
    latitude: number; longitude: number; accuracy: number
    altitude: number | null; heading: number | null; speed: number | null
    timestampISO: string; ageSeconds: number
  }
}

type Status = 'idle' | 'locating' | 'denied' | 'unavailable' | 'timeout' | 'insecure'

const MESSAGE: Record<Exclude<Status, 'idle' | 'locating'>, string> = {
  denied: 'Location permission denied. Click the map instead.',
  unavailable: 'Your device could not provide a location.',
  timeout: 'Locating timed out. Click the map instead.',
  insecure: 'Location needs a secure connection (https or localhost).',
}

export default function MapControls({ map, onLocate }: {
  map: maplibregl.Map | null
  /** Omit to hide the locate button — e.g. on a map that is not a picker. */
  onLocate?: (l: Located) => void
}) {
  const [status, setStatus] = useState<Status>('idle')

  const locate = () => {
    // Distinguish the two failures instead of reporting one word for both.
    if (!navigator.geolocation) {
      console.warn('[locate] navigator.geolocation is undefined')
      setStatus('unavailable')
      return
    }
    if (!window.isSecureContext) {
      console.warn('[locate] insecure context — origin is', window.location.origin)
      setStatus('insecure')
      return
    }
    setStatus('locating')
    navigator.geolocation.getCurrentPosition(
      pos => {
        setStatus('idle')
        const c = pos.coords
        const ageSeconds = Math.round((Date.now() - pos.timestamp) / 1000)
        // RAW, BEFORE ANY TRANSFORM. Logged so a wrong pin can be diagnosed
        // as a bad fix rather than a bad conversion — the two look identical
        // on screen and have completely different fixes.
        console.log('[locate] raw GeolocationCoordinates', {
          latitude: c.latitude, longitude: c.longitude,
          accuracy_m: c.accuracy, altitude: c.altitude,
          heading: c.heading, speed: c.speed,
          timestamp: new Date(pos.timestamp).toISOString(),
          age_seconds: ageSeconds,
          note: c.accuracy > 1000
            ? 'accuracy > 1km: almost certainly IP or coarse wifi, not the device'
            : 'plausible device-level fix',
        })
        onLocate?.({
          lat: c.latitude,
          lon: c.longitude,
          accuracyM: c.accuracy,
          raw: {
            latitude: c.latitude, longitude: c.longitude, accuracy: c.accuracy,
            altitude: c.altitude, heading: c.heading, speed: c.speed,
            timestampISO: new Date(pos.timestamp).toISOString(),
            ageSeconds,
          },
        })
      },
      e => {
        console.warn('[locate] error', { code: e.code, message: e.message })
        setStatus(
          e.code === e.PERMISSION_DENIED ? 'denied'
            : e.code === e.TIMEOUT ? 'timeout'
              : 'unavailable',
        )
      },
      // maximumAge 0: never accept a cached fix. A minute-old position is a
      // minute-old position, and the user pressed the button now.
      // timeout 15s because a real GPS/wifi fix is slower than an IP guess,
      // and returning the fast wrong answer is the failure mode here.
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  }

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

      {status !== 'idle' && status !== 'locating' && (
        <div className="mc-msg">{MESSAGE[status]}</div>
      )}
    </div>
  )
}
