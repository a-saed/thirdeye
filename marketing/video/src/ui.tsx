import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, sans } from "./theme";

// A fade-and-rise for any element, starting `at` seconds into its scene.
export const Rise: React.FC<{ at: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ at, children, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div
      style={{
        opacity: interpolate(frame, [at * fps, at * fps + 0.5 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        translate: interpolate(frame, [at * fps, at * fps + 0.6 * fps], ["0px 24px", "0px 0px"], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
        ...style,
      }}
    >
      {children}
    </div>
  );
};

// The brand's hex lattice at 3.5% white, plus a vignette: texture without
// noise, so a flat dark frame does not read as an empty slide.
const HexTexture: React.FC = () => (
  <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
    <defs>
      <pattern id="hex" width="60" height="104" patternUnits="userSpaceOnUse">
        <path d="M30 0 L60 17.3 L60 52 L30 69.3 L0 52 L0 17.3 Z M30 69.3 L30 104" fill="none" stroke="rgba(255,255,255,0.035)" strokeWidth="1.5" />
      </pattern>
      <radialGradient id="vig" cx="50%" cy="42%" r="75%">
        <stop offset="55%" stopColor="rgba(0,0,0,0)" />
        <stop offset="100%" stopColor="rgba(0,0,0,0.55)" />
      </radialGradient>
    </defs>
    <rect width="100%" height="100%" fill="url(#hex)" />
    <rect width="100%" height="100%" fill="url(#vig)" />
  </svg>
);

// Every scene clears its own words in its last 0.35 s, before the next scene's
// words arrive, so a crossfade never shows two headlines on top of each other.
// Inside a Sequence, useVideoConfig() reports that sequence's duration.
export const useExit = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  return interpolate(frame, [durationInFrames - 0.25 * fps, durationInFrames - 0.02 * fps], [1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
};

export const Scene: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => {
  const exit = useExit();
  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas, color: C.text, fontFamily: sans }}>
      <HexTexture />
      <AbsoluteFill style={{ opacity: exit, ...style }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

// A thin progress line across the top of the whole video. Viewers stay for a
// video whose length they can see.
export const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return (
    <div style={{ position: "absolute", left: 0, top: 0, height: 6, width: `${(100 * frame) / (durationInFrames - 1)}%`, background: C.accent, opacity: 0.9 }} />
  );
};

export const Kicker: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 46, color: "#B4BBC1", fontWeight: 400, lineHeight: 1.25, textWrap: "balance" } as React.CSSProperties}>{children}</div>
);

export const Headline: React.FC<{ children: React.ReactNode; size?: number }> = ({ children, size = 84 }) => (
  <div style={{ fontSize: size, fontWeight: 600, lineHeight: 1.1, letterSpacing: -1, textWrap: "balance" } as React.CSSProperties}>{children}</div>
);

// A label tied to a point on a capture: a short accent rule, then the words.
export const Callout: React.FC<{ at: number; title: string; body?: string }> = ({ at, title, body }) => (
  <Rise at={at} style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
    <div style={{ width: 6, alignSelf: "stretch", background: C.accent, borderRadius: 3 }} />
    <div>
      <div style={{ fontSize: 52, fontWeight: 600, lineHeight: 1.15, textWrap: "balance" } as React.CSSProperties}>{title}</div>
      {body && <div style={{ fontSize: 46, color: "#B4BBC1", lineHeight: 1.25, marginTop: 10, textWrap: "balance" } as React.CSSProperties}>{body}</div>}
    </div>
  </Rise>
);

// Kinetic headline: each word rises in on its own, 60 ms apart. Words are
// split on spaces only, so the sentence still wraps like normal text.
export const Words: React.FC<{ at: number; text: string; style?: React.CSSProperties; stagger?: number }> = ({ at, text, style, stagger = 0.06 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ textWrap: "balance", ...style } as React.CSSProperties}>
      {text.split(" ").map((w, i) => {
        const t0 = (at + i * stagger) * fps;
        // A headline that starts at 0 is on screen whole in the first frame:
        // LinkedIn autoplays from there and may use it as the poster.
        if (at === 0) return <span key={i} style={{ display: "inline-block", marginRight: "0.26em" }}>{w}</span>;
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              marginRight: "0.26em",
              opacity: interpolate(frame, [t0, t0 + 0.35 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
              translate: interpolate(frame, [t0, t0 + 0.5 * fps], ["0px 0.45em", "0px 0em"], {
                extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1),
              }),
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

// A small brand mark in the top-right corner, so a viewer who leaves after
// five seconds still saw the name. Hidden from `hideFrom` (the end card).
export const CornerMark: React.FC<{ hideFrom: number }> = ({ hideFrom }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const o = interpolate(frame, [hideFrom - 0.4 * fps, hideFrom], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", right: 40, top: 34, display: "flex", alignItems: "center", gap: 12, opacity: 0.85 * o, fontFamily: sans }}>
      <svg viewBox="0 0 100 115.47" width={30} height={35}>
        <path fill={C.accent} fillRule="evenodd" d="M50 0 L100 28.87 L100 86.6 L50 115.47 L0 86.6 L0 28.87 Z M50 9.24 L92 33.48 L92 81.99 L50 106.23 L8 81.99 L8 33.48 Z" />
        <circle fill={C.accent} cx={50} cy={57.735} r={15} />
      </svg>
      <div style={{ fontSize: 28, letterSpacing: 5, color: C.text }}>THIRD <span style={{ color: C.accent, fontWeight: 600 }}>EYE</span></div>
    </div>
  );
};
