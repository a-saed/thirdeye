import React from "react";
import { C, SAFE_X, mono } from "../theme";
import { Headline, Kicker, Rise, Scene } from "../ui";

// Five data sources. OpenStreetMap is NOT one of them: it is used only for
// address search and contributes nothing to a report (see the playbook's
// "claims we must not make"). The first cut of this video said six.
const SOURCES = ["Overture Maps", "Foursquare", "Kontur Population", "GHSL", "Google Open Buildings"];

export const Sources: React.FC = () => (
  <Scene>
    <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: 0, bottom: 200, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <Rise at={0.35}><Headline>Five open data sources.</Headline></Rise>
      <div style={{ marginTop: 64, display: "flex", flexDirection: "column", gap: 22 }}>
        {SOURCES.map((s, i) => (
          <Rise key={s} at={0.75 + i * 0.25}>
            <div style={{ display: "inline-block", fontFamily: mono, fontSize: 46, padding: "16px 32px", borderRadius: 999, border: `2px solid ${C.accent}`, color: C.text }}>{s}</div>
          </Rise>
        ))}
      </div>
      <Rise at={2.55} style={{ marginTop: 72 }}>
        <Headline size={64}>No data? The map stays grey.</Headline>
      </Rise>
      <Rise at={3.15} style={{ marginTop: 20 }}>
        <Kicker>Every figure names its sources and its date.</Kicker>
      </Rise>
    </div>
  </Scene>
);
