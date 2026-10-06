// THE ONLY SOURCE OF NUMBERS IN THIS VIDEO. Written by `npm run capture`,
// which refuses to write it unless the live app's screens agree with its API.
// Never type a number into a scene; read it from here.
import live from "../public/live.json";

export type Live = typeof live;
export { live };

export const sourcesDiffer = (r: number | null) => (r ? (1 / r).toFixed(2) : null);
export const fmtInt = (n: number) => n.toLocaleString("en-US");
export const host = new URL(live.base).host;
