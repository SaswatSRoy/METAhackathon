"""Margin's MCP server: the tools give the same verified answers as the notebook, and a real
MCP client can list and call them over stdio."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from server import mcp_server as ms  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WRONG = ["∫ 2x cos(x^2) dx", "= -sin(x^2) + C"]
RIGHT_SO_FAR = ["∫ x cos(x) dx", "= x sin(x) - ∫ sin(x) dx"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def test_check_steps_finds_the_wrong_line():
    out = ms.check_steps(WRONG)
    assert out["first_wrong"] == "L2"
    assert [l["status"] for l in out["lines"]] == ["start", "wrong"]
    assert out["notes"] and out["worded_by"] == "rules"


def test_hint_never_gives_the_answer_below_level_3():
    out = ms.give_hint(WRONG, hint_level=1)
    assert out["first_wrong"] == "L2" and out["notes"]
    assert out["written_steps"] == []
    assert ms.give_hint(WRONG, hint_level=3)["written_steps"]      # level 3 shows the fix


def test_next_step_is_one_verified_step():
    out = ms.next_step(RIGHT_SO_FAR)
    assert len(out["written_steps"]) == 1
    step = out["written_steps"][0]
    assert ms.check_steps(RIGHT_SO_FAR + [step])["first_wrong"] is None


def test_finish_answer_reaches_the_answer():
    out = ms.finish_answer(RIGHT_SO_FAR)
    assert out["written_steps"]
    assert ms.check_steps(RIGHT_SO_FAR + out["written_steps"])["finished"]


def test_explain_typeset_graph_differentiate():
    why = ms.explain_rule(RIGHT_SO_FAR)
    assert 1 <= len(why["explanation"]) <= 3
    assert ms.typeset_lines(RIGHT_SO_FAR)["typeset"][0]["latex"]
    g = ms.sketch_graph(["∫ 2x dx", "= x^2 + C"])["graph"]
    assert g["fn"] and len(g["points"]) <= ms.GRAPH_POINTS + 1
    d = ms.differentiate_check(["∫ 2x dx", "= x^2 + C"])
    assert any(m["kind"] == "tick" for m in d["marks"])


def test_ask_margin_offline_routes_by_keywords():
    out = ms.ask_margin(WRONG, "check my work")
    assert out["mode"] == "check" and out["first_wrong"] == "L2"
    assert out["agent_trace"][0]["tool"] == "route"


def test_meta_tools_need_a_key_and_bad_input_is_refused(tmp_path):
    assert "MODEL_API_KEY" in ms.read_handwriting("page.png")["error"]
    with pytest.raises(ValueError):
        ms.check_steps([])
    with pytest.raises(ValueError):
        ms.check_steps(["x" * 501])
    with pytest.raises(ValueError):
        ms._image_data_url(str(tmp_path / "missing.png"))


def test_real_client_over_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: v for k, v in os.environ.items() if k != "MODEL_API_KEY"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "server.mcp_server"], cwd=str(ROOT), env=env)

    async def go():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool("check_steps", {"lines": WRONG})
            return names, res

    names, res = asyncio.run(go())
    assert {"check_steps", "give_hint", "next_step", "explain_rule", "finish_answer",
            "sketch_graph", "typeset_lines", "differentiate_check", "read_handwriting", "ask_margin"} <= names
    assert not res.isError
    assert res.structuredContent["first_wrong"] == "L2"
