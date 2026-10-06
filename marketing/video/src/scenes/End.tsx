import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, mono } from "../theme";
import { Rise, Scene } from "../ui";

// The icon draws itself: the hexagon traces on, then the eye settles in.
// Geometry from web/public/brand/icon-teal.svg (outer hex, 8-unit wall, r=15 eye).
const HEX = "M50 4 L96 30.5 L96 84.9 L50 111.4 L4 84.9 L4 30.5 Z";

const Icon: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const draw = interpolate(frame, [0, 0.9 * fps], [1, 0], { extrapolateRight: "clamp", easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const eye = interpolate(frame, [0.7 * fps, 1.1 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.back(2.2)) });
  return (
    <svg viewBox="0 0 100 115.47" width={150} height={173} style={{ overflow: "visible", filter: "drop-shadow(0 0 30px rgba(69,201,165,0.35))" }}>
      <path d={HEX} fill="none" stroke={C.accent} strokeWidth={8} strokeLinejoin="miter" pathLength={1} strokeDasharray="1 1" strokeDashoffset={draw} strokeLinecap="butt" strokeOpacity={interpolate(frame, [3, 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
      <circle cx={50} cy={57.735} r={15} fill={C.accent} style={{ scale: String(eye), transformOrigin: "50px 57.7px" }} />
    </svg>
  );
};

export const End: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <Scene style={{ alignItems: "center", justifyContent: "center", textAlign: "center" }}>
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 36%, rgba(69,201,165,${interpolate(frame, [0, 1.2 * fps], [0, 0.18], { extrapolateRight: "clamp" })}), rgba(16,19,21,0) 55%)` }} />
      <div style={{ marginTop: 40, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <Icon />
        <Rise at={1.0} style={{ marginTop: 40 }}>
          <div style={{ fontSize: 96, letterSpacing: 14, fontWeight: 400 }}>THIRD <span style={{ color: C.accent, fontWeight: 600 }}>EYE</span></div>
          <div style={{ fontFamily: mono, fontSize: 28, letterSpacing: 8, color: C.muted, marginTop: 8 }}>LOCATION INTELLIGENCE</div>
        </Rise>
        <Rise at={1.4} style={{ marginTop: 70 }}>
          <div style={{ fontSize: 36, fontWeight: 600, background: C.accent, color: C.canvas, padding: "22px 34px", whiteSpace: "nowrap", borderRadius: 999 }}>Check the street before you sign the lease.</div>
        </Rise>
        <Rise at={1.8} style={{ marginTop: 44 }}>
          <div style={{ fontSize: 40, fontWeight: 600, color: C.text }}>Free. No sign-up. Link in the post.</div>
        </Rise>
        <Rise at={2.1} style={{ marginTop: 16 }}>
          <div style={{ fontSize: 34, color: "rgba(230,233,236,0.78)" }}>Cairo · Giza · Qalyubiya · Alexandria</div>
        </Rise>
      </div>
    </Scene>
  );
};
