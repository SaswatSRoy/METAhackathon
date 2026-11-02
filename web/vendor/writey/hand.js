// Copyright (c) 2026 Writey contributors. MIT License, see ./LICENSE.
// Ported from Writey (MIT), github.com/lagoonitself/writey, packages/inkscript/src/hand.ts:
// TypeScript types stripped, made a browser ES module (no build step).
// Change for Margin: the original turns paths into ink-engine strokes with per-point times;
// Margin animates SVG paths, so this keeps only the timing (when each path starts, how long
// it takes), from the same speed / pen-up / travel model.

// Pen paths (page points) get human-ish timing, so AI ink can be animated as it is "written".

/** Writing speed in points per millisecond (about twice a calm human hand). */
export const SPEED = 0.3;
const PEN_UP_MS = 45;

const pathLength = p => {
  let n = 0;
  for (let i = 2; i + 1 < p.length; i += 2) n += Math.hypot(p[i] - p[i - 2], p[i + 1] - p[i - 1]);
  return Math.max(n, 0.5);                                  // a dot still takes a moment
};

/** Start time and duration (ms) of each flat [x, y, x, y, …] path, drawn one after another. */
export function penTimes(paths, { speed = 1, startAt = 0 } = {}) {
  const v = SPEED * speed;
  const times = [];
  let t = startAt;
  let prev = null;
  for (const p of paths) {
    if (p.length < 2) { times.push({ at: t, dur: 0 }); continue; }
    if (prev) t += PEN_UP_MS + Math.hypot(p[0] - prev[0], p[1] - prev[1]) / (v * 4);
    const dur = pathLength(p) / v;
    times.push({ at: t, dur });
    t += dur;
    prev = [p.at(-2), p.at(-1)];
  }
  return { times, end: t };
}
