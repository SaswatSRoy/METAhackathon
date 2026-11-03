"""Live voice over WebSockets: the page streams microphone audio, Meta streams words back.

    browser ──(binary PCM frames)──► /ws/voice ──► wss://api.meta.ai/v1/asr/realtime
    browser ◄──(JSON: ready, transcript, error)── /ws/voice ◄── Muse Voice Transcribe

The API key stays on the server: the page talks only to /ws/voice, and this module opens the
Meta socket with the key in the handshake frame (Meta reads it there, not from a header).

Audio from the page: 16-bit little-endian mono PCM at 24 kHz, about 80 ms per frame. The page ends
input with {"type": "endStream"}; the server passes it on and relays Meta's last words before closing.

Serverless hosts (Vercel) can't hold a socket open, so /api/health reports `realtime: false` there and
the page records a clip and uses /api/transcribe instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from . import meta_client

log = logging.getLogger("margin.realtime")

MAX_FRAME_BYTES = 32 * 1024          # 80 ms of 24 kHz PCM is 3840 bytes
MAX_SESSION_S = 180                  # one command never needs more than three minutes
HANDSHAKE_TIMEOUT_S = 10
FLUSH_TIMEOUT_S = 10                 # wait this long for Meta's last words after endStream
RELAYED = {"transcript", "speechComplete", "error"}


def available() -> bool:
    """Live voice needs the key and a host that keeps sockets open."""
    if meta_client.is_offline() or os.getenv("VERCEL") or os.getenv("MARGIN_REALTIME", "1") == "0":
        return False
    try:
        import websockets  # noqa: F401
    except ImportError:
        return False
    return True


def realtime_url() -> str:
    explicit = os.getenv("META_REALTIME_URL")
    if explicit:
        return explicit
    base = meta_client.base_url().rstrip("/")
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/asr/realtime"


def handshake() -> dict[str, Any]:
    return {
        "authorization": {"accessToken": f"Bearer {meta_client.api_key()}"},
        "audioEncoding": "PCM_24KHZ",
        "model": meta_client.VOICE_MODEL,
        "mode": "PUSH_TO_TALK",
    }


def relay_message(raw: str | bytes) -> dict[str, Any] | None:
    """Keep only the fields the page needs from one of Meta's frames."""
    try:
        m = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("type") not in RELAYED:
        return None
    if m["type"] == "error":
        return {"type": "error", "message": str(m.get("message") or "Meta voice error")[:200]}
    return {"type": m["type"], "transcript": str(m.get("transcript") or ""), "final": bool(m.get("final", m["type"] == "speechComplete"))}


async def _refuse(ws: WebSocket, message: str) -> None:
    await ws.send_json({"type": "error", "message": message})
    await ws.close(code=1011)


async def voice_socket(ws: WebSocket) -> None:
    await ws.accept()
    if not available():
        await _refuse(ws, "Live voice isn't available on this server")
        return
    if not meta_client.circuit_breaker.allow_request() or not meta_client.rate_limiter.allow():
        await _refuse(ws, "Meta is busy, try again in a moment")
        return

    import websockets

    try:
        up = await websockets.connect(realtime_url(), open_timeout=15, max_size=1 << 20)
    except Exception as exc:
        meta_client.circuit_breaker.record_failure()
        log.warning("Meta realtime connect failed: %s", type(exc).__name__)
        await _refuse(ws, "Couldn't reach Meta's live voice")
        return

    try:
        await up.send(json.dumps(handshake()))
        try:
            ack = json.loads(await asyncio.wait_for(up.recv(), HANDSHAKE_TIMEOUT_S))
        except Exception:
            ack = {}
        if not isinstance(ack, dict) or "sessionId" not in ack:
            msg = (relay_message(json.dumps(ack)) or {}).get("message") if isinstance(ack, dict) else None
            log.warning("Meta realtime handshake refused: %s", msg or ack)
            await _refuse(ws, f"Meta refused live voice{': ' + msg if msg else ''}")
            return
        meta_client.circuit_breaker.record_success()
        await ws.send_json({"type": "ready", "session": ack["sessionId"]})

        async def page_to_meta() -> None:
            started = time.monotonic()
            while True:
                left = MAX_SESSION_S - (time.monotonic() - started)
                if left <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.receive(), left)
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    break
                if msg.get("type") == "websocket.disconnect":
                    break
                data, text = msg.get("bytes"), msg.get("text")
                if data:
                    if len(data) > MAX_FRAME_BYTES:
                        break
                    await up.send(data)
                elif text:
                    try:
                        if json.loads(text).get("type") == "endStream":
                            break
                    except (ValueError, AttributeError):
                        pass
            try:
                await up.send(json.dumps({"type": "endStream"}))
            except Exception:
                pass

        async def meta_to_page() -> None:
            async for raw in up:
                out = relay_message(raw)
                if out:
                    await ws.send_json(out)

        sender = asyncio.create_task(page_to_meta())
        receiver = asyncio.create_task(meta_to_page())
        await sender
        try:
            await asyncio.wait_for(receiver, FLUSH_TIMEOUT_S)
        except asyncio.TimeoutError:
            receiver.cancel()
        except Exception as exc:                       # Meta closed with an error code
            log.warning("Meta realtime ended: %s", exc)
            reason = getattr(exc, "reason", "") or ""
            if reason:
                try:
                    await ws.send_json({"type": "error", "message": f"Meta live voice stopped: {reason[:120]}"})
                except Exception:
                    pass
    finally:
        try:
            await up.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
