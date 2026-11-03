// Pause suggestions: when the student stops writing for a moment on a page with maths, a few
// small ranked chips appear by the pen ("What's next?", "Check this", "Tidy", "Graph it", "Why?").
// Idea from PenEcho (github.com/erickong/penecho); this is Margin's own implementation.
import { PAGE_W, PAGE_H } from './ink.js';
import { isMath } from './handwriting.js';

const PAUSE_MS = 2000, SHOW_MS = 6000;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export const CHIPS = {
  next: { label: 'What’s next?', say: 'what’s next?', mode: 'next' },
  check: { label: 'Check this', say: 'check my work', mode: 'check' },
  tidy: { label: 'Tidy', say: 'tidy my writing', mode: 'typeset' },
  graph: { label: 'Graph it', say: 'sketch the graph', mode: 'graph' },
  why: { label: 'Why?', say: 'why does this work?', mode: 'why' },
  more: { label: 'More help', say: 'more please, be more specific', mode: 'hint' },
};

/** Ranks the chips for the row the student just wrote. `ctx`: { text, handwritten, hinted }. */
export function rankChips({ text = '', handwritten = false, hinted = false } = {}) {
  const t = String(text).trim();
  const score = { next: 2, check: 1.6, tidy: 1 };
  if (/=\s*$/.test(t)) score.next += 3;                                  // "… =": what comes next
  if (/\+\s*C\s*$|=\s*-?[\d.]+(\/\d+)?\s*$|=\s*[^=]*\bC\b\s*$/.test(t)) score.check += 3;   // looks finished
  if (/=/.test(t) && !/=\s*$/.test(t)) score.check += 0.6;
  if (handwritten && !t) score.tidy += 0.8;                              // handwriting only: a neat copy helps
  if (/^\s*∫|^\s*int\b|d\/dx|^\s*[fgy]\s*(\(x\))?\s*=/.test(t)) score.next += 0.5;
  const ranked = Object.keys(score).sort((a, b) => score[b] - score[a]);
  const out = hinted ? ['why', ...ranked.slice(0, 2)] : ranked.slice(0, 3);
  if (/∫|\bint\b|d\/dx|\b[fgy]\s*(\(x\))?\s*=|\bsin|\bcos|\btan|\bln|\be\^|x\^|x²|x³/.test(t)) out.push('graph');
  return out;
}

export class Suggest {
  constructor(page, { nb, onPick, enabled, canShow, hinted }) {
    Object.assign(this, { page, nb, onPick, enabled, canShow, hinted });
    this.el = Object.assign(document.createElement('div'), { className: 'suggest gone', hidden: true });
    this.el.setAttribute('role', 'toolbar');
    this.el.setAttribute('aria-label', 'Suggestions from Meta');
    this.el.addEventListener('pointerdown', e => e.stopPropagation());
    page.append(this.el);
    page.addEventListener('pointerdown', e => { if (!this.el.contains(e.target)) this.hide(); }, true);         // any pen stroke dismisses them
  }
  // Called whenever the student writes: (re)starts the pause timer.
  poke() {
    clearTimeout(this.timer);
    this.hide();
    if (!this.enabled()) return;
    this.timer = setTimeout(() => this.pause(), PAUSE_MS);
  }
  cancel() { clearTimeout(this.timer); this.hide(); }

  // The row next to the pen's last position, or the last typed line.
  context() {
    const lines = this.nb.lines(), { x, y } = this.nb.lastPoint;
    const near = lines.filter(l => y >= l.bbox[1] - 30 && y <= l.bbox[1] + l.bbox[3] + 30).sort((a, b) => Math.abs(a.bbox[0] + a.bbox[2] - x) - Math.abs(b.bbox[0] + b.bbox[2] - x))[0];
    const line = near || lines.at(-1);
    const strokes = this.nb.items.filter(it => it.type === 'stroke' && !it.hl && it.by !== 'meta').length;   // the student's, not Meta's
    return { lines, line, strokes };
  }
  pageHasMath() {
    const { lines, strokes } = this.context();
    return lines.some(l => isMath(l.text)) || strokes >= 3;
  }
  pause() {
    if (!this.enabled() || !this.canShow() || this.nb.active || this.nb.input || !this.pageHasMath()) return;
    if (!['pen', 'type'].includes(this.nb.tool) || this.nb.sel?.length) return;   // not while selecting or erasing
    const { line, strokes } = this.context();
    const handwritten = strokes >= 3 && (!line || this.nb.lastPoint.y > line.bbox[1] + line.bbox[3] + 20);
    this.show(rankChips({ text: handwritten ? '' : line?.text || '', handwritten, hinted: this.hinted() }));
  }
  // Shows chips by the pen (or at `at`, page px).
  show(keys, at = null) {
    clearTimeout(this.fade);
    const { x, y } = at || this.nb.lastPoint;
    const k = 1 / Math.max(0.3, this.nb.scale || 1);
    this.el.replaceChildren(...keys.map((key, i) => {
      const c = CHIPS[key];
      const b = Object.assign(document.createElement('button'), { type: 'button', textContent: c.label });
      b.dataset.chip = key;
      b.style.animationDelay = `${i * 60}ms`;
      b.onclick = e => { e.stopPropagation(); this.hide(); this.onPick(c); };
      return b;
    }));
    const W = 120 * keys.length * k;
    Object.assign(this.el.style, { left: `${clamp(x + 22, 100, PAGE_W - W - 10)}px`, top: `${clamp(y - 12, 70, PAGE_H - 40)}px`, transform: `scale(${k})` });
    this.el.hidden = false;
    requestAnimationFrame(() => this.el.classList.remove('gone'));
    this.fade = setTimeout(() => this.hide(), SHOW_MS);
  }
  hide() {
    clearTimeout(this.fade);
    if (this.el.hidden) return;
    this.el.classList.add('gone');
    setTimeout(() => { if (this.el.classList.contains('gone')) this.el.hidden = true; }, 420);
  }
  get visible() { return !this.el.hidden && !this.el.classList.contains('gone'); }
}
