"""Live voice socket: the page streams PCM, the server relays it to Meta's realtime ASR with the key
in the handshake, and Meta's words come back to the page."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from server import app as app_module, meta_client, realtime

client = TestClient(app_module.app)


class FakeMeta:
    """Stands in for wss://api.meta.ai/v1/asr/realtime."""

    def __init__(self, ack=None):
        self.sent, self.ack = [], ack if ack is not None else {"sessionId": "sess_live"}
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, bytes):
            n = sum(len(d) for d in self.sent if isinstance(d, bytes))
            await self.inbox.put(json.dumps({"type": "transcript", "transcript": "help" if n < 8000 else "help me", "final": False}))
        elif json.loads(data).get("type") == "endStream":
            await self.inbox.put(json.dumps({"type": "audioProgress", "audioProcessedMs": 160}))
            await self.inbox.put(json.dumps({"type": "transcript", "transcript": "help me with this", "final": True}))
            await self.inbox.put(None)

    async def recv(self):
        return json.dumps(self.ack)

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self.inbox.get()
        if m is None:
            raise StopAsyncIteration
        return m

    async def close(self):
        pass


@pytest.fixture
def live(monkeypatch):
    import websockets
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.delenv("VERCEL", raising=False)
    meta_client.rate_limiter.reset()
    meta_client.circuit_breaker.reset()
    fake, seen = FakeMeta(), {}

    async def connect(url, **kw):
        seen["url"] = url
        return fake
    monkeypatch.setattr(websockets, "connect", connect)
    return fake, seen


def test_health_says_whether_live_voice_works(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.delenv("VERCEL", raising=False)
    assert client.get("/api/health").json()["realtime"] is True
    monkeypatch.setenv("VERCEL", "1")                      # serverless: no sockets
    assert client.get("/api/health").json()["realtime"] is False
    monkeypatch.delenv("VERCEL")
    monkeypatch.delenv("MODEL_API_KEY")
    assert client.get("/api/health").json()["realtime"] is False


def test_socket_refuses_when_offline(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json()["type"] == "error"


def test_streams_audio_to_meta_and_words_back(live):
    fake, seen = live
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json() == {"type": "ready", "session": "sess_live"}
        ws.send_bytes(b"\x00\x01" * 1920)                  # 80 ms of 24 kHz PCM
        assert ws.receive_json()["transcript"] == "help"
        ws.send_bytes(b"\x00\x01" * 1920)
        ws.send_bytes(b"\x00\x01" * 1920)
        ws.receive_json()
        last = ws.receive_json()
        ws.send_text(json.dumps({"type": "endStream"}))
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("final"):
                break
    hs = json.loads(fake.sent[0])
    assert hs["authorization"]["accessToken"] == "Bearer test-key"
    assert hs["audioEncoding"] == "PCM_24KHZ" and hs["model"] == meta_client.VOICE_MODEL
    assert seen["url"].startswith("wss://") and seen["url"].endswith("/asr/realtime")
    assert last["transcript"] == "help me"
    assert msgs[-1] == {"type": "transcript", "transcript": "help me with this", "final": True}
    assert all(m["type"] != "audioProgress" for m in msgs)  # only what the page needs
    assert json.loads(fake.sent[-1]) == {"type": "endStream"}
    assert "test-key" not in json.dumps(msgs)


def test_refused_handshake_is_reported(live):
    fake, _ = live
    fake.ack = {"type": "error", "message": "bad model"}
    with client.websocket_connect("/ws/voice") as ws:
        m = ws.receive_json()
    assert m["type"] == "error" and "bad model" in m["message"]


def test_oversized_frame_ends_the_stream(live):
    fake, _ = live
    with client.websocket_connect("/ws/voice") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00" * (realtime.MAX_FRAME_BYTES + 2))
        while not ws.receive_json().get("final"):
            pass
    assert not any(isinstance(d, bytes) and len(d) > realtime.MAX_FRAME_BYTES for d in fake.sent)
    assert json.loads(fake.sent[-1]) == {"type": "endStream"}
