# Margin

Meta Global AI Developer Hackathon 2026. A calculus assistant that lives inside your notebook page.

You write your working with a pen. When you call it ("Hey Meta, help me with this integral",
or press `/`), it reads the page, checks every step with a computer algebra engine, and
**writes a hint in red-pencil handwriting next to the exact line that went wrong**. Ask again
(or tap the hint) and the hint gets more specific; at level 3 it writes a faint "ghost" of the
next line. Say "just give me the answer" and it writes out the rest of the working.

No chat box: everything the assistant says is ink on the page.

**The notebook:** a shelf of notebooks, pages with thumbnails, pressure-sensitive pen (Apple Pencil),
highlighter, lasso, movable text boxes, photos and PDF pages, pinch zoom, autosave, PNG/PDF export,
and it installs on the iPad home screen (Safari → Share → Add to Home Screen) and works offline.

**What Meta can do on the page:** hints (3 levels, then a faint "ghost" of the next line), check my work,
just give me the answer, tidy my writing into typed maths, and sketch the graph. Covers indefinite and
definite integrals and derivatives (product rule, chain rule). Muse Spark 1.3 runs as a tool-calling
agent; every piece of maths it writes comes from the SymPy referee.

![Margin catching a sign slip](docs/screenshot.png)

## How it works

```
pen strokes / typed lines ──► Muse Spark 1.3 reads the page into math lines
                               │
                               ▼
                        SymPy referee (server/checker.py)
                        each line must equal the last; antiderivatives compared by
                        differentiating; diagnoses sign slips, missing constant
                        factors, power-rule slips, "differentiated instead", missing + C
                               │
                               ▼
              Muse Spark 1.3 phrases the verdict as a ≤8-word hint (never decides correctness)
                               │
                               ▼
              page writes circle / note / tick / underline / ghost / write annotations
```

- Meta models: **Muse Spark 1.3** (page reading, intent, hint wording), **Muse Voice Transcribe**
  (voice commands when browser Web Speech is missing or fails).
- Live voice over WebSockets: the page streams the mic to `/ws/voice`, which relays it to Meta's realtime
  transcription (`wss://api.meta.ai/v1/asr/realtime`, key kept on the server) and sends the words back as
  you speak. Works where the server keeps sockets open (`start.sh`, Docker, Hugging Face Spaces, Render).
  Vercel functions can't, so there the page records a clip and sends it to `/api/transcribe` instead.
- API contract between page and server: [docs/CONTRACT.md](docs/CONTRACT.md).
- Optional decision router (Muse Glimmer, off by default): one short JSON call picks the tool and
  hint level, with Spark as the fallback. Data builder, eval and fine-tuning: [docs/ROUTER.md](docs/ROUTER.md).

## Run it

One command: `./start.sh` (Mac/Linux) or double-click `start.bat` (Windows), then open http://localhost:8000.
Put your `MODEL_API_KEY` in `.env` to turn on handwriting reading.

Manual:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # put your MODEL_API_KEY from https://dev.meta.ai in it
.venv/bin/uvicorn server.app:app --reload
# open http://localhost:8000  (⋯ menu → "Try the demo problem", then press / → Help me)
.venv/bin/pytest -q         # offline, no network
```

Without `MODEL_API_KEY` it runs in **offline mode**: typed lines (T tool) are checked and hints
come from rules; handwriting can only be read with the key.

## Use Margin from other agent apps (MCP server)

`server/mcp_server.py` makes Margin's tools available over the Model Context Protocol, so Claude Desktop,
Claude Code, Cursor or any MCP client can check calculus working with the same SymPy referee.

| Tool | What it returns | Needs the key? |
|------|-----------------|----------------|
| `check_steps` | status of every line, the first wrong line and a note on the mistake | no |
| `give_hint` | a hint on the first wrong line (levels 1-2 never reveal the answer) | no (Spark words it when set) |
| `next_step` | one next step, checked by SymPy before it is returned | no |
| `explain_rule` | why the step works: rule, formula, how it applies | no (Spark words it when set) |
| `finish_answer` | the remaining verified steps and the answer | no |
| `typeset_lines` | each line as neat text and LaTeX | no |
| `sketch_graph` | graph points for the function (and the antiderivative) | no |
| `differentiate_check` | differentiates an antiderivative to check it | no |
| `read_handwriting` | the lines read from a photo of a page (Muse Spark vision) | yes |
| `ask_margin` | Margin's own Muse Spark agent chains the tools for a request like "help me" | yes (keywords without it) |

Lines are a list of strings, one step each, e.g. `["∫ 2x cos(x^2) dx", "= sin(x^2) + C"]`.

```bash
.venv/bin/pip install -r requirements-mcp.txt
.venv/bin/python -m server.mcp_server              # stdio
.venv/bin/python -m server.mcp_server --http 8765  # streamable HTTP at http://127.0.0.1:8765/mcp
```

Claude Desktop (Settings → Developer → Edit Config), with your own path:

```json
{
  "mcpServers": {
    "margin": {
      "command": "/path/to/METAhackathon/.venv/bin/python",
      "args": ["-m", "server.mcp_server"],
      "cwd": "/path/to/METAhackathon"
    }
  }
}
```

Claude Code: `claude mcp add margin -- /path/to/METAhackathon/.venv/bin/python -m server.mcp_server`
(run it from the repo folder). The key is read from `.env` as for the notebook.

## Put it online (free https, needed for voice on iPad)

Hugging Face Spaces: create a Space with the **Docker** SDK, push this repo to it, and add
`MODEL_API_KEY` under Settings → Variables and secrets (as a secret). The Dockerfile serves on port 7860.
Render also works: New Web Service → this repo → Docker, and add `MODEL_API_KEY` as an environment variable.

## Limitations (MVP)

- Lives in its own web notebook, not inside GoodNotes/Notability (no plugin APIs). OneNote add-in
  or a Xournal++ plugin are the realistic routes into a real app.
- The live Meta API path (page reading, hint wording, transcription) has not been run yet: needs a key.
- Maths scope: first-year integrals and derivatives; quotient-rule mistakes get only a generic hint.
- Voice wake word needs Chrome; not tested on a real iPad / Apple Pencil. Notebooks are saved in the browser on one device (no accounts or sync).

## Credits

- **[Writey](https://github.com/lagoonitself/writey)** (MIT): Meta's handwriting engine and maths
  layout are ported from Writey's `packages/inkscript` (glyph data, seeded jitter and `handLine`,
  `textBox` / `writeText`, the LaTeX parser and `layoutMath`: fractions, scripts, ∫ with limits, √,
  sized brackets; pen timing). Plain-JS port in `web/vendor/writey/` with its licence. The
  Accept / Redo / Discard preview for written answers is Writey's idea too.
- **EMS Allure** (SIL Open Font License 1.1, `web/vendor/writey/OFL.txt`) and the **Hershey fonts**
  (via hersheytext, MIT): the glyph stroke data Meta writes with.
- **[PenEcho](https://github.com/erickong/penecho)**: inspired the pause suggestions (chips by the pen
  when you stop writing). No PenEcho code is used.
