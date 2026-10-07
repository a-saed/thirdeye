import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { live, fmtInt } from "../live";
import { C, SAFE_X, SAFE_Y } from "../theme";
import { Headline, Kicker, Rise, Scene } from "../ui";

// Area search: start from criteria, not from a place.
export const Search: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return (
    <Scene>
      <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: SAFE_Y }}>
        <Rise at={0.35}><Headline size={76}>Or let it find the streets for you.</Headline></Rise>
        <Rise at={0.85} style={{ marginTop: 20 }}>
          <Kicker>Rank areas by the one measure you choose.</Kicker>
        </Rise>
      </div>
      <Rise at={1.25} style={{ position: "absolute", left: SAFE_X, top: 450, width: 904, height: 620, overflow: "hidden", borderRadius: 16, border: `2px solid ${C.border}` }}>
        {/* Phone-width capture of the search page: its header, the map of
            matching cells, and the match count. */}
        <Img
          src={staticFile("captures/search-phone.png")}
          style={{ width: 904, marginTop: -400, scale: interpolate(frame, [0, durationInFrames], [1, 1.05]), transformOrigin: "50% 40%" }}
        />
        <div style={{ position: "absolute", right: 10, bottom: 10, fontSize: 18, color: "rgba(255,255,255,0.75)", background: "rgba(16,19,21,0.75)", padding: "4px 10px", borderRadius: 6 }}>© CARTO © OpenStreetMap contributors</div>
      </Rise>

      <Rise at={2.15} style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: 1094 }}>
        <div style={{ fontSize: 46, color: "#B4BBC1" }}>{fmtInt(live.searchMatches ?? 0)} areas match “cafés”</div>
      </Rise>
    </Scene>
  );
};
