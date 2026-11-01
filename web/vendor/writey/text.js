// Copyright (c) 2026 Writey contributors. MIT License, see ./LICENSE.
// Ported from Writey (MIT), github.com/lagoonitself/writey, packages/inkscript/src/text.ts:
// TypeScript types stripped, imports made browser ES modules (no build step).
import { inlineMath, shiftPaths, writeText } from './layout.js';
// A sentence of handwriting with inline $math$, wrapped to a width (em).
const WORD_GAP = 0.34;
/** Splits text into words and $…$ / \(…\) math, keeping which pieces had a space before them. */
export function splitInline(text) {
    const out = [];
    const re = /\$\$([^$]+)\$\$|\$([^$]+)\$|\\\((.+?)\\\)|(\s+)|([^\s$]+)/g;
    let space = false;
    for (const m of text.matchAll(re)) {
        const math = m[1] ?? m[2] ?? m[3];
        if (math !== undefined) {
            out.push({ kind: 'math', text: math, space });
            space = false;
        }
        else if (m[4])
            space = true;
        else if (m[5]) {
            out.push({ kind: 'word', text: m[5], space });
            space = false;
        }
    }
    return out;
}
export function layoutParagraph(text, maxWidth, rng) {
    const pieces = splitInline(text).map((p) => ({
        box: p.kind === 'math' ? inlineMath(p.text, rng) : writeText(p.text, rng),
        space: p.space,
    }));
    const lines = [];
    let line = { w: 0, h: 0, d: 0, paths: [] };
    for (const p of pieces) {
        const gap = line.paths.length && p.space ? WORD_GAP : line.paths.length ? 0.04 : 0;
        if (line.paths.length && line.w + gap + p.box.w > maxWidth) {
            lines.push(line);
            line = { w: 0, h: 0, d: 0, paths: [] };
        }
        const x = line.w + (line.paths.length ? gap : 0);
        line.paths.push(...shiftPaths(p.box.paths, x, 0));
        line.w = x + p.box.w;
        line.h = Math.max(line.h, p.box.h);
        line.d = Math.max(line.d, p.box.d);
    }
    if (line.paths.length)
        lines.push(line);
    return lines;
}
/** Stacks wrapped lines into one box, `leading` em apart baseline to baseline at least. */
export function stackLines(lines, leading = 1.35) {
    const out = { w: 0, h: 0, d: 0, paths: [] };
    let y = 0;
    lines.forEach((l, i) => {
        if (i > 0)
            y += Math.max(leading, lines[i - 1].d + l.h + 0.2);
        out.paths.push(...shiftPaths(l.paths, 0, y));
        out.w = Math.max(out.w, l.w);
        if (i === 0)
            out.h = l.h;
    });
    out.d = y + (lines.at(-1)?.d ?? 0);
    return out;
}
