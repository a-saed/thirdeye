import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame, useDelayRender, useVideoConfig,
} from "remotion";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { cellToBoundary, gridDisk, latLngToCell } from "h3-js";
import { live } from "../live";
import { C, SAFE_X, SAFE_Y, sans } from "../theme";
import { Words, useExit } from "../ui";

// THE OPENING: Greater Cairo's coverage, then down to one street, then the
// cafes around it appear nearest-first while the counter counts them. The
// number shown is the number of dots on screen, and the dots are the records
// the live app returned (public/data/places-a.json, written by capture).

const SITE: [number, number] = [live.a.lon, live.a.lat];
const CAIRO: [number, number] = [31.24, 30.06];
const Z_START = 9.4;
const Z_END = 14.7;
const FLY_END = 2.6; // seconds: the counter must start by ~3 s
const RES = 9; // the report's resolution; k matches live.k

// Same paint as the app (web/src/map/paint.mjs, web/src/tokens.css).
const NO_DATA = "#3F4A52";
const COVERAGE_OPACITY = (f: number) => ["*",
  ["match", ["get", "conf"], "corroborated", 0.85, "single_source", 0.38, 0.58],
  ["case", ["==", ["get", "inh"], 1], 1, 0.35], f];
const SRC_COLOR = ["match", ["get", "source"], "both", C.accent, "overture", "#6BA8D8", "#C77FD0"];

type Place = { lat: number; lon: number; source: string; flagged: boolean };

const ringFeature = () => {
  const cells = gridDisk(latLngToCell(live.a.lat, live.a.lon, RES), live.k);
  return {
    type: "FeatureCollection" as const,
    features: cells.map(c => ({
      type: "Feature" as const,
      properties: {},
      geometry: { type: "Polygon" as const, coordinates: [cellToBoundary(c, true)] },
    })),
  };
};

// ZOOM TOWARDS A POINT. The site's offset from the screen centre, in pixels,
// shrinks smoothly to zero while the zoom rises. Interpolating centre and zoom
// independently made the street wander across the frame mid-flight. At zoom z
// a lon/lat offset spans 2^z times more pixels, so the geographic offset is
// scaled back by 2^(Z_START - z) to keep the pixel offset on its own curve.
const camera = (t: number) => {
  const zoom = Z_START + (Z_END - Z_START) * Easing.bezier(0.65, 0, 0.35, 1)(t);
  const off = (1 - Easing.bezier(0.4, 0, 0.2, 1)(t)) * 2 ** (Z_START - zoom);
  return {
    center: [SITE[0] + (CAIRO[0] - SITE[0]) * off, SITE[1] + (CAIRO[1] - SITE[1]) * off] as [number, number],
    zoom,
    // The question holds the top and the count the bottom; the street sits
    // in the band between them (centre at y = 440 + (1350-440-440)/2 = 675).
    padding: { top: 440, bottom: 440, left: 0, right: 0 },
  };
};

export const MapIntro: React.FC = () => {
  const ref = useRef<HTMLDivElement>(null);
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const { delayRender, continueRender } = useDelayRender();
  const [map, setMap] = useState<Map | null>(null);
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [loading] = useState(() => delayRender("Loading map"));

  useEffect(() => {
    if (!ref.current) return;
    maplibregl.setWorkerUrl(URL.createObjectURL(new Blob(
      [`import "https://unpkg.com/maplibre-gl@${maplibregl.getVersion()}/dist/maplibre-gl-worker.mjs";`],
      { type: "text/javascript" })));
    const m = new maplibregl.Map({
      container: ref.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: CAIRO, zoom: Z_START,
      interactive: false, attributionControl: false, fadeDuration: 0,
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    m.on("load", async () => {
      // Labels move and re-place as the zoom changes, which reads as jitter;
      // the story here is the hexes and the dots, not the place names.
      for (const l of m.getStyle().layers ?? []) if (l.type === "symbol") m.removeLayer(l.id);
      const [cov, pl] = await Promise.all([
        fetch(staticFile("data/coverage-res8.geojson")).then(r => r.json()),
        fetch(staticFile("data/places-a.json")).then(r => r.json() as Promise<Place[]>),
      ]);
      // Nearest first: the count grows outward from the door.
      const d = (p: Place) => (p.lat - live.a.lat) ** 2 + ((p.lon - live.a.lon) * Math.cos((live.a.lat * Math.PI) / 180)) ** 2;
      pl.sort((a, b) => d(a) - d(b));
      m.addSource("cov", { type: "geojson", data: cov });
      m.addLayer({
        id: "cov-fill", type: "fill", source: "cov",
        paint: {
          "fill-color": ["match", ["get", "conf"], "corroborated", C.accent, "single_source", C.amber, NO_DATA],
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], 11, COVERAGE_OPACITY(1), 13, COVERAGE_OPACITY(0.45), 15, COVERAGE_OPACITY(0.12)] as never,
        },
      });
      m.addSource("ring", { type: "geojson", data: ringFeature() });
      m.addLayer({ id: "ring-fill", type: "fill", source: "ring", paint: { "fill-color": C.amber, "fill-opacity": 0 } });
      m.addLayer({ id: "ring-line", type: "line", source: "ring", paint: { "line-color": "#ffffff", "line-opacity": 0, "line-width": 2 } });
      m.addSource("pts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "pts", type: "circle", source: "pts",
        paint: {
          "circle-color": SRC_COLOR as never,
          "circle-radius": ["*", 15, ["get", "s"]] as never,
          "circle-opacity": ["case", ["get", "flagged"], 0.35, 0.95] as never,
          "circle-stroke-width": ["case", ["get", "flagged"], 3, 1.5] as never,
          "circle-stroke-color": ["case", ["get", "flagged"], C.amber, "rgba(0,0,0,0.6)"] as never,
        },
      });
      m.addSource("site", { type: "geojson", data: { type: "Point", coordinates: SITE } });
      m.addLayer({ id: "site", type: "circle", source: "site", paint: { "circle-radius": 13, "circle-color": C.accent, "circle-stroke-color": "#fff", "circle-stroke-width": 4 } });
      m.jumpTo(camera(0));
      m.once("idle", () => { setPlaces(pl); setMap(m); continueRender(loading); });
    });
  }, [continueRender, loading]);

  useEffect(() => {
    if (!map || !places) return;
    const h = delayRender("Rendering map frame");
    const s = frame / fps;
    map.jumpTo(camera(Math.min(1, s / FLY_END)));
    const ringIn = interpolate(s, [FLY_END - 0.6, FLY_END + 0.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    map.setPaintProperty("ring-line", "line-opacity", 0.7 * ringIn);
    map.setPaintProperty("ring-fill", "fill-opacity", 0.12 * ringIn);
    // One dot every ~0.08 s after the fly-in; each pops in over 0.25 s.
    const shown = places.map((p, i) => {
      const t0 = FLY_END + 0.15 + i * 0.075;
      const k = interpolate(s, [t0, t0 + 0.25], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.back(2)) });
      return { p, k };
    }).filter(x => x.k > 0);
    (map.getSource("pts") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: shown.map(({ p, k }) => ({
        type: "Feature", properties: { source: p.source, flagged: p.flagged, s: k },
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      })),
    });
    map.once("idle", () => continueRender(h));
    map.triggerRepaint();
  }, [map, places, frame, fps, delayRender, continueRender]);

  const exit = useExit();
  const s = frame / fps;
  const count = places ? places.filter((_, i) => s >= FLY_END + 0.15 + i * 0.075).length : 0;
  const counterIn = interpolate(s, [FLY_END, FLY_END + 0.35], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas, fontFamily: sans, color: C.text }}>
      <div ref={ref} style={{ position: "absolute", width, height }} />
      {/* Readability band behind the words; the map keeps the middle. */}
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(rgba(16,19,21,0.95) 0%, rgba(16,19,21,0.85) 26%, rgba(16,19,21,0) 38%, rgba(16,19,21,0) 58%, rgba(16,19,21,0.88) 68%, rgba(16,19,21,0.95) 100%)` }} />
      <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: SAFE_Y, opacity: exit }}>
        <Words at={0} stagger={0} text="Opening your next café?" style={{ fontSize: 46, color: C.muted }} />
        <Words at={0} text={`How many competitors are already a\u00A0${live.walkMinutes}-minute walk away?`} style={{ fontSize: 80, fontWeight: 600, lineHeight: 1.08, marginTop: 18, letterSpacing: -1 }} />
      </div>
      <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, bottom: 215, opacity: counterIn * exit }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 28 }}>
          <div style={{ fontSize: 210, fontWeight: 600, color: C.accent, lineHeight: 0.9, letterSpacing: -6, fontVariantNumeric: "tabular-nums", minWidth: 250 }}>{count}</div>
          <div style={{ fontSize: 52, fontWeight: 600, lineHeight: 1.1 }}>cafés within<br />~{live.walkMinutes} minutes on foot</div>
        </div>
        <div style={{ fontSize: 44, color: "#B4BBC1", marginTop: 18 }}>{live.a.name}, Cairo · as of {live.a.competitorsAsOf}</div>
      </div>
      <div style={{ position: "absolute", right: 88, top: 1350 - 500, fontSize: 20, color: "rgba(255,255,255,0.55)" }}>© CARTO © OpenStreetMap contributors</div>
    </AbsoluteFill>
  );
};
