import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database.db import engine
from app.main import app
from app.stt import FAKE_TRANSCRIPT, TranscriptionError, get_transcriber
from tests.conftest import ADMIN_TOKEN, reset_database

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 256
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def client():
    asyncio.run(reset_database())
    asyncio.run(engine.dispose())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def new_session(client) -> str:
    return client.post("/api/chat/sessions").json()["session_id"]


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


# Chat


def test_create_session_returns_an_empty_summary(client):
    body = client.post("/api/chat/sessions").json()
    assert body["message_count"] == 0
    assert body["outcome"] is None


def test_chat_turn_is_persisted(client):
    sid = new_session(client)
    reply = client.post("/api/chat", json={"session_id": sid, "message": "My order ORD-10015 arrived damaged"})
    assert reply.status_code == 200
    assert "$89.99" in reply.json()["response"]

    messages = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]


@pytest.mark.parametrize(
    "payload",
    [
        {"message": ""},
        {"message": "\x00\x01  "},
        {"message": "x" * 2001},
        {"session_id": "../../etc", "message": "hi"},
    ],
)
def test_chat_rejects_bad_input(client, payload):
    assert client.post("/api/chat", json=payload).status_code == 422


def test_stream_emits_logs_then_the_response(client):
    sid = new_session(client)
    params = {"session_id": sid, "message": "ORD-09980 is defective"}
    with client.stream("GET", "/api/chat/stream", params=params) as response:
        body = "".join(response.iter_text())

    events = [line.removeprefix("event: ").strip() for line in body.splitlines() if line.startswith("event:")]
    assert events[0] == "log"
    assert events[-2:] == ["response", "done"]
    response_data = body.split("event: response", 1)[1].split("data: ", 1)[1].splitlines()[0]
    assert "senior agent" in json.loads(response_data)["text"]


def test_stream_rejects_invalid_session_id(client):
    assert client.get("/api/chat/stream", params={"session_id": "bad id!", "message": "hi"}).status_code == 400


# Admin


@pytest.mark.parametrize("path", ["/api/admin/stats", "/api/admin/sessions", "/api/admin/customers"])
def test_admin_routes_require_the_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong-token-wrong-token"}).status_code == 401
    assert client.get(path, headers=AUTH).status_code == 200


def test_admin_is_disabled_without_a_configured_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    assert client.get("/api/admin/stats", headers=AUTH).status_code == 503


def test_admin_stats_reflect_recorded_decisions(client):
    sid = new_session(client)
    client.post("/api/chat", json={"session_id": sid, "message": "ORD-10015 arrived damaged"})
    stats = client.get("/api/admin/stats", headers=AUTH).json()
    assert (stats["total_sessions"], stats["approved"], stats["total_refunded"]) == (1, 1, 89.99)

    sessions = client.get("/api/admin/sessions", headers=AUTH).json()
    assert sessions[0]["customer_id"] == "CUST-007"
    logs = client.get(f"/api/admin/sessions/{sid}/logs", headers=AUTH).json()
    assert logs[-1]["event_type"] == "decision"


def test_admin_session_limit_is_bounded(client):
    assert client.get("/api/admin/sessions?limit=101", headers=AUTH).status_code == 422


# Voice


def upload(client, data: bytes, content_type: str = "audio/webm", filename: str = "clip.webm"):
    return client.post("/api/voice/transcribe", files={"file": (filename, data, content_type)})


@pytest.mark.parametrize(("data", "content_type"), [(WEBM, "audio/webm;codecs=opus"), (WAV, "audio/wav")])
def test_transcribe_accepts_real_audio(client, data, content_type):
    response = upload(client, data, content_type)
    assert response.status_code == 200
    assert response.json() == {"text": FAKE_TRANSCRIPT}


def test_transcribe_rejects_non_audio_types(client):
    assert upload(client, b"hello", "text/plain", "notes.txt").status_code == 415


def test_transcribe_rejects_mislabelled_content(client):
    assert upload(client, b"<html>not audio</html>", "audio/webm").status_code == 415


def test_transcribe_rejects_empty_files(client):
    assert upload(client, b"").status_code == 400


def test_transcribe_enforces_the_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_audio_bytes", 1024)
    assert upload(client, WEBM + b"\x00" * 2048).status_code == 413


def test_transcription_failure_is_a_bad_gateway(client):
    async def failing(filename: str, data: bytes) -> str:
        raise TranscriptionError("upstream down")

    app.dependency_overrides[get_transcriber] = lambda: failing
    assert upload(client, WEBM).status_code == 502


# CORS


def test_cors_allows_the_frontend_origin_only(client):
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    ok = client.options("/api/chat", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in ok.headers

    evil = client.options("/api/chat", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in evil.headers
