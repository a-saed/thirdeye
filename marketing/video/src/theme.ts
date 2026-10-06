// Brand tokens, copied from web/src/tokens.css so the video and the app read
// as one product. Change them there first.
import { loadFont as loadSans } from "@remotion/google-fonts/IBMPlexSans";
import { loadFont as loadMono } from "@remotion/google-fonts/IBMPlexMono";

export const sans = loadSans("normal", { weights: ["400", "600"], subsets: ["latin"] }).fontFamily;
export const mono = loadMono("normal", { weights: ["400"], subsets: ["latin"] }).fontFamily;

export const C = {
  canvas: "#101315",
  surface: "#191D21",
  surface2: "#22272B",
  border: "rgba(255, 255, 255, 0.14)",
  text: "#E6E9EC",
  muted: "#9BA3AA",
  accent: "#45C9A5",
  amber: "#D8A33F",
};

// 1080 x 1350 (4:5). Safe area per the Remotion layout rules: key text at
// least 80 px from the sides and 100 px from top and bottom.
export const W = 1080;
export const H = 1350;
export const SAFE_X = 88;
export const SAFE_Y = 110;
export const FPS = 30;
