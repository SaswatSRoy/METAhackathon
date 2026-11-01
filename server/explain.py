"""'Why does this work?': short rule explanations keyed by the referee's detection.

Everything here is deterministic. The topic comes from the checker (the diagnosis of the
first wrong step, or the technique the latest step used), the formula comes from a fixed
template, and only the plain-word prose lines may be reworded by Muse Spark
(meta_client.phrase_why), which never sees or writes the maths.

Public API:
    TEMPLATES                 topic -> Template
    topic_for(result)         -> Topic (what to explain, on which line, with which context)
    explanation(result)       -> dict  {"topic", "target", "mistake", "lines", "latex", "latex_line"}
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sympy as sp

from . import checker
from .checker import CheckResult, pretty

MAX_WORDS = 12


@dataclass(frozen=True)
class Template:
    prose: tuple[str, ...]      # plain-word lines (≤ 12 words each); Muse Spark may reword these
    formula: str | None = None  # the rule as plain ink text, shown as one line of the note
    latex: str | None = None    # the same rule in LaTeX, for the page to typeset


TEMPLATES: dict[str, Template] = {
    "by_parts": Template(
        ("Parts swaps a hard integral for an easier one.",
         "Pick u so it gets simpler when you differentiate it."),
        "∫ u dv = uv − ∫ v du", r"\int u\,dv = uv - \int v\,du"),
    "u_sub": Template(
        ("Spot an inner function whose derivative is also there.",
         "Rename the inner function u and the integral gets simple."),
        "∫ f(g(x)) g′(x) dx = ∫ f(u) du", r"\int f(g(x))\,g'(x)\,dx = \int f(u)\,du"),
    "power_rule_int": Template(
        ("Raise the power by one, then divide by the new power.",
         "This works for every power except minus one."),
        "∫ xⁿ dx = xⁿ⁺¹/(n+1) + C", r"\int x^n\,dx = \frac{x^{n+1}}{n+1} + C"),
    "power_rule_der": Template(
        ("Bring the power down in front, then lower it by one.",
         "Constants on their own differentiate to zero."),
        "d/dx xⁿ = n xⁿ⁻¹", r"\frac{d}{dx}\,x^n = n\,x^{n-1}"),
    "chain_rule": Template(
        ("Differentiate the outside, keep the inside, then multiply.",
         "Never forget the derivative of the inner function."),
        "d/dx f(g(x)) = f′(g(x)) · g′(x)", r"\frac{d}{dx}\,f(g(x)) = f'(g(x))\,g'(x)"),
    "product_rule": Template(
        ("Each factor takes a turn being differentiated.",
         "So the answer always has two terms."),
        "(uv)′ = u′v + uv′", r"(uv)' = u'v + uv'"),
    "sin_sign": Template(
        ("Cosine differentiates to minus sine.",
         "So integrating sine gives minus cosine."),
        "∫ sin x dx = −cos x + C", r"\int \sin x\,dx = -\cos x + C"),
    "trig_derivative": Template(
        ("Sine turns into cosine, cosine turns into minus sine.",
         "Watch the minus sign on the cosine one."),
        "d/dx sin x = cos x,  d/dx cos x = −sin x",
        r"\frac{d}{dx}\sin x = \cos x,\quad \frac{d}{dx}\cos x = -\sin x"),
    "constant_factor": Template(
        ("Constants slide straight through the integral sign.",
         "An inner multiple like two means dividing by two."),
        "∫ k f(x) dx = k ∫ f(x) dx", r"\int k\,f(x)\,dx = k\int f(x)\,dx"),
    "plus_c": Template(
        ("Constants differentiate to zero, so any constant fits.",
         "The plus C stands for all of those answers."),
        "d/dx (F(x) + C) = F′(x)", r"\frac{d}{dx}\left(F(x) + C\right) = F'(x)"),
    "ftc": Template(
        ("Find any antiderivative, then subtract its values at the ends.",
         "No plus C needed here: it cancels out."),
        "∫ₐᵇ f(x) dx = F(b) − F(a)", r"\int_a^b f(x)\,dx = F(b) - F(a)"),
    "reverse": Template(
        ("Integrating undoes differentiating, so work backwards.",
         "Ask which function has this as its derivative.")),
    "differentiate": Template(
        ("This asks for a derivative, not an antiderivative.",
         "Differentiate each piece with a rule you know.")),
    "sign": Template(
        ("A single sign flipped somewhere in this step.",
         "Check each minus sign as you expand the brackets.")),
    "general": Template(
        ("Each line must be equal to the line above it.",
         "Redo this step slowly from the previous line.")),
}

# Diagnosis kind (checker.diagnose) -> topic. power_rule, factor, sign, not_equal need context.
MISTAKE_TOPIC = {
    "product_rule": "product_rule", "chain_rule": "chain_rule", "trig_sign": "trig_derivative",
    "differentiated": "reverse", "integrated": "differentiate", "antiderivative": "ftc",
    "limits": "ftc", "no_limits": "ftc", "arithmetic": "ftc", "factor": "constant_factor",
}


@dataclass
class Topic:
    topic: str
    target: str | None
    mistake: bool
    context: str | None = None  # a maths line from SymPy, e.g. "Here u = x, dv = cos x dx"


# --------------------------------------------------------------------------- detection


def _chain_exprs(result: CheckResult, upto: checker.LineResult | None = None) -> list[sp.Expr]:
    """Correct expressions of the last problem, in order (stops before `upto`'s wrong part)."""
    lines = result.lines
    end = lines.index(upto) + 1 if upto is not None else len(lines)
    exprs: list[sp.Expr] = []
    seen = False
    for r in lines[:end]:
        p = r.parsed
        if not p.ok:
            continue
        # Same rule as check_lines: a non-"=" line that is a definition or a calculus problem
        # (or the very first readable line) starts a new problem.
        if not p.continuation and (not seen or p.defines or checker.chain_kind(p.parts[0]) != "algebra"):
            exprs = []
        seen = True
        if r is upto:
            exprs.extend(p.parts[:upto.wrong_part or 0])
        elif r.status in ("start", "ok"):
            exprs.extend(p.parts)
    return exprs


def _is_sin_term(f: sp.Expr, var: sp.Symbol) -> bool:
    """c·sin(ax + b)."""
    _, g = f.as_independent(var, as_Add=False)
    return isinstance(g, sp.sin) and g.args[0].is_polynomial(var) and sp.degree(g.args[0], var) == 1


def _integral_topic(prev: sp.Expr, var: sp.Symbol) -> tuple[str, str | None]:
    integs = sorted((i for i in prev.atoms(sp.Integral) if len(i.limits[0]) == 1), key=sp.default_sort_key)
    if not integs:
        return "reverse", None
    f = integs[0].function
    split = checker._parts_split(f, var)
    if split:
        u, dv = split
        return "by_parts", f"Here u = {pretty(u)}, dv = {pretty(dv)} d{var}"
    if _is_sin_term(f, var):
        return "sin_sign", None
    sub = checker.u_sub(f, var)
    if sub is not None:
        return "u_sub", f"Here u = {pretty(sub[0])}"
    if f.is_polynomial(var):
        return "power_rule_int", None
    return "reverse", None


def _derivative_topic(result: CheckResult, exprs: list[sp.Expr]) -> tuple[str, str | None]:
    f = checker._bare_derivative(exprs[0]) if exprs else None
    var = result.var
    if f is None:
        return "differentiate", None
    split = checker._product_split(f, var)
    if split:
        return "product_rule", f"Here u = {pretty(split[0])}, v = {pretty(split[1])}"
    inner = checker._inner_args(f, var)
    if inner:
        return "chain_rule", f"Inner function: {pretty(inner[0])}"
    if f.atoms(sp.sin, sp.cos) and not f.is_Add:
        return "trig_derivative", None
    if f.is_polynomial(var):
        return "power_rule_der", None
    return "differentiate", None


def _technique(result: CheckResult, exprs: list[sp.Expr], prev: sp.Expr | None) -> tuple[str, str | None]:
    """The rule behind the step that follows `prev` in the last problem (`exprs`: its chain)."""
    if result.chain == "definite":
        return "ftc", None
    if result.chain == "derivative":
        return _derivative_topic(result, exprs)
    if result.chain == "integral" and prev is not None:
        return _integral_topic(prev, result.var)
    return "general", None


def topic_for(result: CheckResult) -> Topic:
    """What to explain: the first mistake if there is one, else the latest step's rule."""
    wrong = result.wrong
    if wrong is not None:
        d = wrong.diagnosis
        exprs = _chain_exprs(result, wrong)
        prev = exprs[-1] if exprs else None
        topic = MISTAKE_TOPIC.get(d.kind)
        context = None
        if d.kind == "power_rule":
            topic = "power_rule_der" if result.chain == "derivative" else "power_rule_int"
        elif d.kind == "sign":
            topic = "sign"
            if result.chain == "integral" and prev is not None and _integral_topic(prev, result.var)[0] == "sin_sign":
                topic = "sin_sign"
        elif topic is None:
            topic, context = _technique(result, exprs, prev)
        elif topic in ("product_rule", "chain_rule"):
            found, ctx = _derivative_topic(result, exprs)
            context = ctx if found == topic else None
        return Topic(topic, wrong.id, True, context)

    good = [r for r in result.lines if r.status in ("ok", "start")]
    if not good:
        return Topic("general", result.lines[-1].id if result.lines else None, False)
    last = good[-1]
    if last.note == "Don't forget + C":
        return Topic("plus_c", last.id, True)
    exprs = _chain_exprs(result)
    # Explain the step that produced the latest line (or, with only the problem, the step to take).
    prev = exprs[-2] if len(exprs) >= 2 else (exprs[-1] if exprs else None)
    topic, context = _technique(result, exprs, prev)
    return Topic(topic, last.id, False, context)


# --------------------------------------------------------------------------- output


_MATHY = re.compile(r"[=^∫/\d′'+()·−\[\]|]|\b(?![aAI]\b)[a-zA-Z]\b")


def is_plain_words(line: str) -> bool:
    """A prose line with no maths in it (so a model may reword it), at most 12 words."""
    return bool(line.strip()) and len(line.split()) <= MAX_WORDS and not _MATHY.search(line)


def explanation(result: CheckResult, reword=None) -> dict:
    """Up to three short lines: the idea, the formula (if any), and a context line or tip.

    `reword(prose_lines, topic)` may return reworded prose lines (Muse Spark online); any
    line it returns that is not plain words of at most 12 words keeps the template's line.
    """
    t = topic_for(result)
    tpl = TEMPLATES[t.topic]
    prose = list(tpl.prose)
    if reword is not None:
        try:
            new = reword(prose, t.topic)
        except Exception:
            new = None
        if isinstance(new, list) and len(new) == len(prose):
            prose = [n.strip() if isinstance(n, str) and is_plain_words(n) else old
                     for n, old in zip(new, prose)]
    lines = [prose[0]]
    latex_line = None
    if tpl.formula:
        latex_line = len(lines)
        lines.append(tpl.formula)
    if t.context and len(t.context.split()) <= MAX_WORDS:
        lines.append(t.context)
    elif len(prose) > 1:
        lines.append(prose[1])
    return {"topic": t.topic, "target": t.target, "mistake": t.mistake, "lines": lines[:3],
            "latex": tpl.latex, "latex_line": latex_line}
