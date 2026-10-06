import React from "react";
import { Img, staticFile } from "remotion";
import { live } from "../live";
import { C, SAFE_X } from "../theme";
import { Headline, Kicker, Rise, Scene } from "../ui";

// Two shortlisted sites, measured side by side: the compare page's two maps,
// and the competitor counts it shows (checked against the API by capture).
// The compare page's two maps are one capture (3216 x 810, 3x): each half is
// one site. Shown as two tiles, each with its own count beneath it.
const HALF = 3216 / 2;
const TILE_W = 440;
const TILE_H = 236;
const MapTile: React.FC<{ side: 0 | 1 }> = ({ side }) => (
  <div style={{ width: TILE_W, height: TILE_H, overflow: "hidden", borderRadius: 14, border: `2px solid ${C.border}` }}>
    <Img src={staticFile("captures/compare-minis.png")} style={{ width: (3216 / HALF) * TILE_W, marginLeft: side === 0 ? 0 : -(TILE_W * 1.0075), marginTop: 0 }} />
  </div>
);

// Which site has fewer competitors per land km² is read from the data, never
// assumed, so a later capture cannot make this sentence false. (Round 2 of
// review caught "fewer by 165%": more than 100% fewer is impossible.)
const [LOWER, HIGHER] = live.a.competitorsPerLandKm2 <= live.b.competitorsPerLandKm2 ? [live.a, live.b] : [live.b, live.a];

export const Compare: React.FC = () => (
  <Scene>
    <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: 0, bottom: 200, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <Rise at={0.2}><Kicker>Two sites on the shortlist?</Kicker></Rise>
      <Rise at={0.35} style={{ marginTop: 16 }}>
        <Headline size={80}>{live.a.name} vs {live.b.name}</Headline>
      </Rise>
      <div style={{ marginTop: 56, display: "flex", gap: 24 }}>
        <Rise at={0.7}>
          <MapTile side={0} />
          <div style={{ fontSize: 150, fontWeight: 600, color: C.accent, lineHeight: 1, marginTop: 30, letterSpacing: -4 }}>{live.a.competitors}</div>
          <div style={{ fontSize: 40, color: C.text, marginTop: 8 }}>cafés · {live.a.name}</div>
          <div style={{ fontSize: 34, color: C.muted, marginTop: 6 }}>{live.a.competitorsPerLandKm2.toFixed(1)} per land km²</div>
        </Rise>
        <Rise at={1.0}>
          <MapTile side={1} />
          <div style={{ fontSize: 150, fontWeight: 600, color: "#8B93E6", lineHeight: 1, marginTop: 30, letterSpacing: -4 }}>{live.b.competitors}</div>
          <div style={{ fontSize: 40, color: C.text, marginTop: 8 }}>cafés · {live.b.name}</div>
          <div style={{ fontSize: 34, color: C.muted, marginTop: 6 }}>{live.b.competitorsPerLandKm2.toFixed(1)} per land km²</div>
        </Rise>
      </div>
      <Rise at={0.7} style={{ fontSize: 18, color: "rgba(255,255,255,0.5)", marginTop: 14 }}>Maps: © CARTO © OpenStreetMap contributors</Rise>
      {/* Say which way is good: for competitors, fewer is better. */}
      <Rise at={1.8} style={{ marginTop: 44 }}>
        <div style={{ fontSize: 50, fontWeight: 600, lineHeight: 1.2, textWrap: "balance" } as React.CSSProperties}>
          {LOWER.name} has fewer cafés per land km²: {LOWER.competitorsPerLandKm2.toFixed(1)} vs {HIGHER.competitorsPerLandKm2.toFixed(1)}.
        </div>
        <div style={{ fontSize: 40, color: C.muted, marginTop: 12, lineHeight: 1.3, textWrap: "balance" } as React.CSSProperties}>
          The app shows who leads on each measure, and by how much. No overall score.
        </div>
      </Rise>
    </div>
  </Scene>
);
