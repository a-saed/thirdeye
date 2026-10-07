import React from "react";
import { Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { live, sourcesDiffer } from "../live";
import { C, SAFE_X, SAFE_Y } from "../theme";
import { Callout, Rise, Scene, Words } from "../ui";

// The real report card, with a camera that walks through its small print.
// The capture is the card at 3x (777 px wide); every box comes from the
// capture run, so highlights land on the lines whatever the layout is.
const CARD_W = 904;
const S = CARD_W / 777;
const CARD_H = 573 * S; // the capture is 573 px tall
const WIN_H = 680; // the window the camera looks through
const ZOOM = 1.45;

type Box = { x: number; y: number; w: number; h: number } | null;
const B = live.cardBoxes as Record<string, Box>;

// Each beat: when it starts (s), which line it is about, and its note.
const corroborated = (live.a.cellsByConfidence as Record<string, number>).corroborated ?? 0;
const BEATS = [
  {
    at: 1.5, box: B.confidence,
    title: "How sure we are, at a glance.",
    body: corroborated === 0
      ? "No area here is confirmed by both sources."
      : `${corroborated} of ${live.a.cellsTotal} areas confirmed by both sources.`,
  },
  {
    at: 5.1, box: B.differ,
    title: `Sources disagree ${sourcesDiffer(live.a.agreementRatio)}× here.`,
    body: "We show the gap instead of hiding it.",
  },
  {
    at: 8.7, box: B.duplicates,
    title: `${live.a.duplicateFlagged} of ${live.a.records} may be duplicates.`,
    body: "Flagged, not hidden.",
  },
];

const centre = (b: Box) => (b ? { x: (b.x + b.w / 2) * S, y: (b.y + b.h / 2) * S } : { x: CARD_W / 2, y: WIN_H / 2 });

// Camera: whole card first, then each beat's line centred at ZOOM.
const useCamera = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = frame / fps;
  // Zoom only as far as the whole line still fits the window, with a margin.
  const fit = (b: Box) => (b ? Math.min(ZOOM, (CARD_W - 56) / (b.w * S)) : 1);
  const shots = [{ at: 0, scale: 1, x: CARD_W / 2, y: WIN_H / 2 }, ...BEATS.map(b => ({ at: b.at, scale: fit(b.box), ...centre(b.box) }))];
  let i = 0;
  while (i < shots.length - 1 && s >= shots[i + 1].at) i++;
  // Move from the previous shot to the current one over 0.7 s.
  const to = shots[i];
  const from = shots[Math.max(0, i - 1)];
  const k = interpolate(s, [to.at, to.at + 0.7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const lerp = (p: number, q: number) => p + (q - p) * k;
  const scale = lerp(from.scale, to.scale);
  const cx = lerp(from.x, to.x);
  const cy = lerp(from.y, to.y);
  // Translate so (cx, cy) in card space lands at the window centre.
  // Keep the camera inside the card: never show past its edges.
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  const tx = clamp(CARD_W / 2 - cx * scale, CARD_W - CARD_W * scale, 0);
  const ty = clamp(WIN_H / 2 - cy * scale, Math.min(0, WIN_H - CARD_H * scale), 0);
  // While zoomed, the window's side edges fade so a crop reads as a camera move.
  const edge = interpolate(scale, [1, 1.15], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return { scale, tx, ty, edge };
};

const Mark: React.FC<{ box: Box; at: number; until?: number }> = ({ box, at, until }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!box) return null;
  const padX = 12, padY = 4, lead = 4;
  const x = box.x * S - padX, y = box.y * S - padY + lead, w = box.w * S + 2 * padX, h = box.h * S + 2 * padY - lead;
  const t0 = (at + 0.5) * fps; // draw once the camera has arrived
  const draw = interpolate(frame, [t0, t0 + 0.5 * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.65, 0, 0.35, 1) });
  const glow = interpolate(frame, [t0 + 0.3 * fps, t0 + 0.8 * fps], [0, 0.14], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const focus = until == null ? 1 : interpolate(frame, [until * fps, until * fps + 0.4 * fps], [1, 0.3], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  // The stroke fades in over its first frames: a zero-length dash still
  // paints a dot at its start.
  const on = interpolate(frame, [t0 + 2, t0 + 5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <g opacity={focus}>
      <rect x={x} y={y} width={w} height={h} rx={14} fill={C.accent} fillOpacity={glow} />
      {/* pathLength 1: the dash is exactly one perimeter, so no stray dashes. */}
      <rect x={x} y={y} width={w} height={h} rx={14} fill="none" stroke={C.accent} strokeOpacity={on} strokeWidth={3.5} pathLength={1} strokeDasharray="1 1" strokeDashoffset={draw} />
    </g>
  );
};

// Holds a note in the shared slot and fades it out when the next one arrives.
const Slot: React.FC<{ to?: number; children: React.ReactNode }> = ({ to, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = to == null ? 1 : interpolate(frame, [to * fps, to * fps + 0.25 * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", inset: 0, opacity: out }}>{children}</div>;
};

export const HowWeKnow: React.FC = () => {
  const cam = useCamera();
  return (
    <Scene>
      <div style={{ position: "absolute", left: SAFE_X, right: SAFE_X, top: SAFE_Y }}>
        <Words at={0.2} text={`${live.a.competitors}. Here's how we know.`} style={{ fontSize: 76, fontWeight: 600, letterSpacing: -1 }} />
        <Rise at={0.45} style={{ marginTop: 36, width: CARD_W, height: WIN_H, overflow: "hidden", borderRadius: 22, background: C.surface2, maskImage: `linear-gradient(90deg, rgba(0,0,0,${1 - cam.edge}) 0, #000 56px, #000 calc(100% - 56px), rgba(0,0,0,${1 - cam.edge}) 100%)` }}>
          <div style={{ position: "relative", width: CARD_W, transformOrigin: "0 0", translate: `${cam.tx}px ${cam.ty}px`, scale: String(cam.scale) }}>
            <Img src={staticFile("captures/report-card.png")} style={{ width: CARD_W, display: "block" }} />
            <svg width={CARD_W} height={WIN_H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
              <Mark box={BEATS[0].box} at={BEATS[0].at} until={BEATS[1].at} />
              <Mark box={BEATS[1].box} at={BEATS[1].at} until={BEATS[2].at} />
              <Mark box={BEATS[2].box} at={BEATS[2].at} />
            </svg>
          </div>
        </Rise>
        <div style={{ position: "relative", marginTop: 44, height: 200 }}>
          <Slot to={BEATS[1].at}><Callout at={BEATS[0].at + 0.3} title={BEATS[0].title} body={BEATS[0].body} /></Slot>
          <Slot to={BEATS[2].at}><Callout at={BEATS[1].at + 0.3} title={BEATS[1].title} body={BEATS[1].body} /></Slot>
          <Slot><Callout at={BEATS[2].at + 0.3} title={BEATS[2].title} body={BEATS[2].body} /></Slot>
        </div>
      </div>
    </Scene>
  );
};
