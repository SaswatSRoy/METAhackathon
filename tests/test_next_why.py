"""Modes "next" (one verified step) and "why" (rule explanation), and `latex` on maths ink."""
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from server import explain, meta_client
from server.app import app
from server.checker import check_lines, latex_for_text
from server.skills import TOOL_SPECS, Toolbox

client = TestClient(app)


def lines(*texts):
    return [{"id": f"L{i}", "text": t, "bbox": [40, 40 + 60 * i, 300, 50]} for i, t in enumerate(texts, 1)]


def assist(*texts, **kw):
    return client.post("/api/assist", json={"lines": lines(*texts), **kw}).json()


def run(tool, *texts, level=1):
    box = Toolbox(lines(*texts), level)
    box.run(tool, {})
    return box.output()


# --------------------------------------------------------------------------- next step


@pytest.mark.parametrize("page, step, after", [
    (("∫ x cos x dx",), "= x sin x - ∫ sin x dx", "L1"),                        # by parts, step 1
    (("∫ x cos x dx", "= x sin x - ∫ sin x dx"), "= x sin x + cos x + C", "L2"),  # by parts, step 2
    (("∫ 2x e^(x^2) dx",), "= e^(x^2) + C", "L1"),                              # u-sub
    (("∫ x^2 dx",), "= x^3/3 + C", "L1"),                                       # power rule
    (("d/dx (x^2 sin x)",), "= (x^2)' sin x + x^2 (sin x)'", "L1"),             # derivative
    (("d/dx sin(x^2)",), "= 2x cos(x^2)", "L1"),
    (("∫_0^1 x^2 dx",), "= [x^3/3]_0^1", "L1"),                                 # definite
    (("∫_0^1 x^2 dx", "= [x^3/3]_0^1"), "= 1/3", "L2"),
])
def test_next_writes_exactly_one_verified_step(page, step, after):
    out = run("next_step", *page)
    assert out["mode"] == "next"
    assert len(out["annotations"]) == 1
    w = out["annotations"][0]
    assert w["kind"] == "write" and w["after"] == after and w["text"] == step
    assert w["latex"].startswith("= ")
    res = check_lines(list(page) + [step])  # the referee accepts the step
    assert res.first_wrong is None and res.lines[-1].status == "ok"


def test_next_after_last_correct_line_skips_unreadable_tail():
    out = run("next_step", "∫ x^2 dx", "= ))((")
    assert out["annotations"][0]["after"] == "L1"


def test_next_on_a_mistake_behaves_like_hint():
    out = run("next_step", "∫ x cos x dx", "= x sin x - ∫ sin x dx", "= x sin x - cos x + C")
    assert out["mode"] == "hint"
    assert {"kind": "circle", "target": "L3"} in out["annotations"]
    note = next(a for a in out["annotations"] if a["kind"] == "note")
    assert note["target"] == "L3"
    assert not any(a["kind"] == "write" for a in out["annotations"])
    assert "hint instead" in out["agent_trace"][-1]["summary"]


def test_next_when_finished_or_missing_c():
    out = run("next_step", "∫ x^2 dx", "= x^3/3 + C")
    assert out["annotations"] == [{"kind": "note", "target": "L2", "text": "That's the answer!", "side": "right"}]
    out = run("next_step", "∫ x^2 dx", "= x^3/3")
    assert out["annotations"][0]["text"] == "Don't forget + C"


def test_next_step_rejected_by_referee_becomes_a_nudge(monkeypatch):
    from server import checker
    monkeypatch.setattr(checker, "solve_remaining", lambda r: ["= x^3 + C"])  # a wrong "step"
    out = run("next_step", "∫ x^2 dx")
    assert [a["kind"] for a in out["annotations"]] == ["note"]
    assert out["annotations"][0]["text"] == "Use the power rule"


def test_next_via_api_and_keywords():
    body = assist("∫ x cos x dx", command="what's next?")
    assert body["mode"] == "next"
    assert [a["kind"] for a in body["annotations"]] == ["write"]
    assert body["agent_trace"][0]["summary"] == "offline: keywords -> next"
    assert assist("∫ x^2 dx", mode="next")["annotations"][0]["text"] == "= x^3/3 + C"


# --------------------------------------------------------------------------- why


@pytest.mark.parametrize("page, topic, target, mistake", [
    (("∫ x cos x dx",), "by_parts", "L1", False),
    (("∫ x cos x dx", "= x sin x - ∫ sin x dx"), "by_parts", "L2", False),
    (("∫ 2x e^(x^2) dx",), "u_sub", "L1", False),
    (("∫ x^2 dx",), "power_rule_int", "L1", False),
    (("∫ x^2 dx", "= x^3 + C"), "power_rule_int", "L2", True),
    (("d/dx x^3",), "power_rule_der", "L1", False),
    (("d/dx sin(x^2)",), "chain_rule", "L1", False),
    (("d/dx sin(x^2)", "= cos(x^2)"), "chain_rule", "L2", True),
    (("d/dx (x^2 sin x)",), "product_rule", "L1", False),
    (("d/dx (x^2 sin x)", "= 2x cos x"), "product_rule", "L2", True),
    (("∫ x cos x dx", "= x sin x - ∫ sin x dx", "= x sin x - cos x + C"), "sin_sign", "L3", True),
    (("d/dx cos x", "= sin x"), "trig_derivative", "L2", True),
    (("∫ cos(2x) dx", "= sin(2x) + C"), "constant_factor", "L2", True),
    (("∫ x^2 dx", "= x^3/3"), "plus_c", "L2", True),
    (("∫_0^1 x^2 dx",), "ftc", "L1", False),
    (("∫_0^1 x^2 dx", "= [x^3/3]_0^1", "= 1/2"), "ftc", "L3", True),
    (("∫ x^2 dx", "= 2x"), "reverse", "L2", True),
])
def test_why_topic_for_each_technique(page, topic, target, mistake):
    ex = explain.explanation(check_lines(list(page)))
    assert (ex["topic"], ex["target"], ex["mistake"]) == (topic, target, mistake)
    assert 1 <= len(ex["lines"]) <= 3
    assert all(len(l.split()) <= 12 for l in ex["lines"])


def test_why_note_shape_and_by_parts_formula():
    out = run("explain_rule", "∫ x cos x dx", "= x sin x - ∫ sin x dx")
    assert out["mode"] == "why"
    [note] = out["annotations"]
    assert note["kind"] == "note" and note["target"] == "L2"
    rows = note["text"].split("\n")
    assert len(rows) == 3 and all(len(r.split()) <= 12 for r in rows)
    assert note["latex"] == r"\int u\,dv = uv - \int v\,du"
    assert rows[note["latex_line"]] == "∫ u dv = uv − ∫ v du"
    assert rows[2] == "Here u = x, dv = cos x dx"


def test_why_on_a_mistake_circles_it():
    out = run("explain_rule", "∫ x cos x dx", "= x sin x - ∫ sin x dx", "= x sin x - cos x + C")
    assert out["annotations"][0] == {"kind": "circle", "target": "L3"}
    assert out["annotations"][1]["latex"] == r"\int \sin x\,dx = -\cos x + C"


def test_templates_are_short_and_formulas_come_with_latex():
    for name, t in explain.TEMPLATES.items():
        assert 1 <= len(t.prose) <= 2, name
        assert all(len(p.split()) <= 12 for p in t.prose), name
        assert (t.formula is None) == (t.latex is None), name


def test_why_reword_keeps_maths_and_rejects_bad_lines():
    res = check_lines(["∫ x cos x dx"])
    ex = explain.explanation(res, reword=lambda prose, topic: ["Trade a tough integral for a kinder one."] * len(prose))
    assert ex["lines"][0] == "Trade a tough integral for a kinder one."
    assert ex["lines"][1] == "∫ u dv = uv − ∫ v du" and ex["latex"] == r"\int u\,dv = uv - \int v\,du"
    # maths, too many words, or the wrong count: template lines stay
    for bad in (["Use u = x here."], ["one two three four five six seven eight nine ten eleven twelve 13"],
                ["fine words", "extra", "more"], None):
        ex = explain.explanation(res, reword=lambda p, t, bad=bad: (bad * len(p)) if bad and len(bad) == 1 else bad)
        assert ex["lines"][0] == explain.TEMPLATES["by_parts"].prose[0]


def test_why_via_api_and_keywords():
    body = assist("∫ x^2 dx", command="why does this work?")
    assert body["mode"] == "why"
    note = body["annotations"][0]
    assert note["kind"] == "note" and "\n" in note["text"] and note["latex"].startswith(r"\int x^n")


@pytest.mark.parametrize("command, intent", [
    ("what's next", "next"), ("whats next?", "next"), ("what’s next", "next"), ("give me the next step", "next"),
    ("what now", "next"), ("continue", "next"), ("keep going", "next"),
    ("why", "why"), ("why is that right?", "why"), ("explain this step", "why"),
    ("how does this work", "why"), ("hey meta help me", "hint"), ("just give me the answer", "answer"),
    ("is this right?", "check"), ("check it by differentiating", "verify"), ("tidy this up", "typeset"),
])
def test_keyword_routing_next_and_why(command, intent):
    assert meta_client.keyword_intent(command) == intent


# --------------------------------------------------------------------------- latex on maths ink


def test_latex_on_write_ghost_typeset():
    body = assist("∫ x cos x dx", command="just give me the answer")
    writes = [a for a in body["annotations"] if a["kind"] == "write"]
    assert writes and all(a["latex"].startswith("= ") for a in writes)
    assert writes[-1]["latex"].endswith("+ C")
    body = assist("∫ x cos x dx", "= x sin x + ∫ sin x dx", command="help", hint_level=3)
    ghost = next(a for a in body["annotations"] if a["kind"] == "ghost")
    assert ghost["latex"].startswith("= ") and r"\int" in ghost["latex"]
    body = assist("∫ x^2 dx", command="tidy this up")
    assert all(a["latex"] for a in body["annotations"] if a["kind"] == "typeset")
    body = assist("∫_0^1 x^2 dx", command="solve it")
    assert [a["latex"] for a in body["annotations"] if a["kind"] == "write"] == [
        r"= \left[ \frac{x^{3}}{3} \right]_{0}^{1}", r"= \frac{1}{3}"]


def test_plain_notes_have_no_latex():
    body = assist("∫ x cos x dx", "= x sin x - ∫ sin x dx", "= x sin x - cos x + C", command="help")
    assert all("latex" not in a for a in body["annotations"] if a["kind"] == "note")


def test_latex_for_text_keeps_equals_and_c_and_never_empty():
    assert latex_for_text("= x^3/3 + C") == r"= \frac{x^{3}}{3} + C"
    assert latex_for_text("f'(x) = 2x").startswith(r"\text{f'(x)} = ")
    assert latex_for_text("= ))((")


# --------------------------------------------------------------------------- agent loop (mocked)


def _resp(content=None, calls=()):
    tool_calls = [NS(id=f"call_{i}", type="function", function=NS(name=n, arguments=json.dumps(a)))
                  for i, (n, a) in enumerate(calls)] or None
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


class FakeClient:
    def __init__(self, script, side_reply="not json at all"):
        self.script, self.side_reply = list(script), side_reply
        self.agent_calls, self.side_calls = [], []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        if "tools" not in kw:
            self.side_calls.append(kw)
            return _resp(self.side_reply)
        self.agent_calls.append(kw)
        return self.script.pop(0) if self.script else _resp("DONE")


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-key")

    def install(script, **kw):
        fake = FakeClient(script, **kw)
        monkeypatch.setattr(meta_client, "_client", lambda: fake)
        return fake
    return install


def test_tool_specs_include_next_and_why():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert {"next_step", "explain_rule"} <= names


def test_agent_calls_next_step(online):
    fake = online([_resp(None, [("next_step", {})]), _resp("DONE")])
    out = meta_client.run_agent("what's next", lines("∫ x cos x dx"), None)
    assert out["mode"] == "next"
    assert [a["kind"] for a in out["annotations"]] == ["write"]
    assert out["annotations"][0]["latex"].startswith("= x ")
    tool_msg = fake.agent_calls[1]["messages"][-1]
    assert json.loads(tool_msg["content"])["summary"].startswith("next step: = x sin x")


def test_agent_calls_explain_rule_and_model_rewords_prose_only(online):
    reply = json.dumps({"lines": ["Swap a tough integral for a friendlier one.", "Choose u that simplifies."]})
    fake = online([_resp(None, [("explain_rule", {})]), _resp("DONE")], side_reply=reply)
    out = meta_client.run_agent("why does this work", lines("∫ x cos x dx"), None)
    assert out["mode"] == "why"
    note = out["annotations"][0]
    rows = note["text"].split("\n")
    assert rows[0] == "Swap a tough integral for a friendlier one."
    assert rows[1] == "∫ u dv = uv − ∫ v du" and rows[2] == "Here u = x, dv = cos x dx"
    assert note["latex"] == r"\int u\,dv = uv - \int v\,du"
    assert fake.side_calls and fake.side_calls[0]["max_tokens"] >= 1500


def test_agent_explain_rule_with_unusable_reword_keeps_template(online):
    online([_resp(None, [("explain_rule", {})]), _resp("DONE")], side_reply="u = x so ∫ = 42")
    out = meta_client.run_agent("explain", lines("∫ x^2 dx"), None)
    assert out["annotations"][0]["text"].split("\n")[0] == explain.TEMPLATES["power_rule_int"].prose[0]


def test_agent_next_then_explain_both_inked(online):
    online([_resp(None, [("next_step", {}), ("explain_rule", {})]), _resp("DONE")])
    out = meta_client.run_agent("what's next and why", lines("∫ x cos x dx"), None)
    assert [a["kind"] for a in out["annotations"]] == ["write", "note"]
    assert [t["tool"] for t in out["agent_trace"]] == ["next_step", "explain_rule"]
