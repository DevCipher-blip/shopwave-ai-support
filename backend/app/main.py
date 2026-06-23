"""
FastAPI application — chat, admin, voice endpoints.
"""

import asyncio
import json
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import run_agent
from app.config import settings
from app.database.db import AsyncSessionLocal, engine
from app.database.models import AgentLog, Base, ChatSession, Customer, Message
from app.database.seed import seed
from app.stt import ALLOWED_AUDIO_TYPES, Transcriber, TranscriptionError, get_transcriber, sniff_audio

# ── Session log broadcast registry ──────────────────────────────────────────
# Maps session_id → list of asyncio.Queue for SSE subscribers
_log_subscribers: dict[str, list[asyncio.Queue]] = {}
# Per-session lock so one conversation cannot interleave with itself while
# separate conversations still run independently.
_session_locks: dict[str, asyncio.Lock] = {}
# Global admin broadcast queue
_admin_queues: list[asyncio.Queue] = []

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
MAX_MESSAGE_LENGTH = 2000
SAFE_FAILURE_RESPONSE = (
    "I couldn't complete that request. Please try again with your order number or the email address on the order."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    seeded = await seed()
    if seeded:
        print(f"Seeded {seeded} customer profiles.")
    yield


app = FastAPI(title="ShopWave AI Refund Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Admin access is disabled. Set ADMIN_TOKEN.")
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(supplied.encode(), settings.admin_token.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        return _normalize_session_id(value)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _normalize_message(value)


class ChatResponse(BaseModel):
    session_id: str
    response: str


class ChatSessionResponse(BaseModel):
    session_id: str
    started_at: str | None
    ended_at: str | None
    outcome: str | None
    refund_amount: float | None
    message_count: int


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: str | None


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_or_create_session(session_id: str | None) -> str:
    sid = _normalize_session_id(session_id) or str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        existing = await db.get(ChatSession, sid)
        if not existing:
            db.add(ChatSession(session_id=sid))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
    return sid


def _normalize_session_id(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    normalized = session_id.strip()
    if not normalized:
        return None
    if not SESSION_ID_RE.fullmatch(normalized):
        raise ValueError("Invalid session_id format")
    return normalized


def _normalize_message(message: str) -> str:
    normalized = CONTROL_CHARS_RE.sub("", message or "").strip()
    if not normalized:
        raise ValueError("Message cannot be empty")
    if len(normalized) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message exceeds {MAX_MESSAGE_LENGTH} characters")
    return normalized


def _get_session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


async def _load_history(session_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Message).where(Message.session_id == session_id).order_by(Message.id))
        return [{"role": message.role, "content": message.content} for message in result.scalars().all()]


async def _persist_turn(session_id: str, user_message: str, response_text: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(Message(session_id=session_id, role="user", content=user_message))
        db.add(Message(session_id=session_id, role="assistant", content=response_text))
        await db.commit()


async def _load_session_summary(session_id: str) -> ChatSessionResponse:
    async with AsyncSessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        message_count = (
            await db.execute(select(func.count(Message.id)).where(Message.session_id == session_id))
        ).scalar() or 0

    return ChatSessionResponse(
        session_id=session.session_id,
        started_at=session.started_at.isoformat() if session.started_at else None,
        ended_at=session.ended_at.isoformat() if session.ended_at else None,
        outcome=session.outcome,
        refund_amount=session.refund_amount,
        message_count=message_count,
    )


async def _run_chat_turn(session_id: str, message: str) -> str:
    lock = _get_session_lock(session_id)
    async with lock:
        history = await _load_history(session_id)

        log_queue: asyncio.Queue = asyncio.Queue()
        if session_id not in _log_subscribers:
            _log_subscribers[session_id] = []
        _log_subscribers[session_id].append(log_queue)

        try:
            response_text = await run_agent(session_id, message, history, log_queue)
        except Exception:
            response_text = SAFE_FAILURE_RESPONSE
        finally:
            subscribers = _log_subscribers.get(session_id, [])
            if log_queue in subscribers:
                subscribers.remove(log_queue)
            if not subscribers and session_id in _log_subscribers:
                del _log_subscribers[session_id]

        while not log_queue.empty():
            log = log_queue.get_nowait()
            if log:
                await _broadcast_log(session_id, log)

        await _persist_turn(session_id, message, response_text)
        return response_text


async def _broadcast_log(session_id: str, log: dict):
    """Push a log event to all SSE subscribers for this session and admin queues."""
    for q in _log_subscribers.get(session_id, []):
        await q.put(log)
    for q in _admin_queues:
        enriched = {**log, "session_id": session_id}
        await q.put(enriched)


# ── Chat endpoint ─────────────────────────────────────────────────────────────


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = await _get_or_create_session(req.session_id)
    response_text = await _run_chat_turn(session_id, req.message)
    return ChatResponse(session_id=session_id, response=response_text)


@app.post("/api/chat/sessions", response_model=ChatSessionResponse)
async def create_chat_session():
    session_id = await _get_or_create_session(None)
    return await _load_session_summary(session_id)


@app.get("/api/chat/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(session_id: str):
    try:
        normalized_session_id = _normalize_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message).where(Message.session_id == normalized_session_id).order_by(Message.id)
        )
        messages = result.scalars().all()

    return [
        ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at.isoformat() if message.created_at else None,
        )
        for message in messages
    ]


# ── Streaming chat endpoint (SSE) ─────────────────────────────────────────────


@app.get("/api/chat/stream")
async def chat_stream(session_id: str, message: str):
    """
    SSE endpoint that streams both agent reasoning logs AND the final response.
    Events: { type: 'log', data: {...} } | { type: 'response', data: '...' } | { type: 'done' }
    """
    try:
        normalized_session_id = _normalize_session_id(session_id)
        normalized_message = _normalize_message(message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sid = await _get_or_create_session(normalized_session_id)

    async def event_generator():
        lock = _get_session_lock(sid)
        async with lock:
            history = await _load_history(sid)
            log_queue: asyncio.Queue = asyncio.Queue()
            if sid not in _log_subscribers:
                _log_subscribers[sid] = []
            _log_subscribers[sid].append(log_queue)

            agent_task = asyncio.create_task(run_agent(sid, normalized_message, history, log_queue))

            try:
                while True:
                    log = await log_queue.get()
                    if log is None:
                        try:
                            response_text = await agent_task
                        except Exception:
                            response_text = SAFE_FAILURE_RESPONSE

                        await _persist_turn(sid, normalized_message, response_text)
                        yield {"event": "response", "data": json.dumps({"text": response_text})}
                        yield {"event": "done", "data": "{}"}
                        break

                    for q in _admin_queues:
                        await q.put({**log, "session_id": sid})
                    yield {"event": "log", "data": json.dumps(log)}

            except asyncio.CancelledError:
                agent_task.cancel()
                raise
            finally:
                subscribers = _log_subscribers.get(sid, [])
                if log_queue in subscribers:
                    subscribers.remove(log_queue)
                if not subscribers and sid in _log_subscribers:
                    del _log_subscribers[sid]

    return EventSourceResponse(event_generator())


# ── Admin SSE stream ──────────────────────────────────────────────────────────


@admin.get("/stream")
async def admin_stream():
    """SSE stream for the admin dashboard: every agent event across all sessions.

    sse-starlette sends keep-alive pings, so an idle dashboard stays connected.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _admin_queues.append(queue)

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield {"event": "log", "data": json.dumps(event)}
        finally:
            if queue in _admin_queues:
                _admin_queues.remove(queue)

    return EventSourceResponse(event_generator())


# ── Admin REST endpoints ──────────────────────────────────────────────────────


@admin.get("/sessions")
async def list_sessions(limit: Annotated[int, Query(ge=1, le=100)] = 20):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ChatSession).order_by(desc(ChatSession.started_at)).limit(limit))
        sessions = result.scalars().all()

    return [
        {
            "session_id": s.session_id,
            "customer_id": s.customer_id,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "outcome": s.outcome,
            "refund_amount": s.refund_amount,
        }
        for s in sessions
    ]


@admin.get("/sessions/{session_id}/logs")
async def get_session_logs(session_id: str):
    try:
        session_id = _normalize_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentLog).where(AgentLog.session_id == session_id).order_by(AgentLog.id))
        logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "node": log.node,
            "event_type": log.event_type,
            "content": log.content,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@admin.get("/stats")
async def get_stats():
    async with AsyncSessionLocal() as db:
        total_sessions = (await db.execute(select(func.count(ChatSession.session_id)))).scalar()
        approved = (
            await db.execute(select(func.count(ChatSession.session_id)).where(ChatSession.outcome == "approve"))
        ).scalar()
        denied = (
            await db.execute(select(func.count(ChatSession.session_id)).where(ChatSession.outcome == "deny"))
        ).scalar()
        escalated = (
            await db.execute(select(func.count(ChatSession.session_id)).where(ChatSession.outcome == "escalate"))
        ).scalar()
        total_refunded = (
            await db.execute(select(func.sum(ChatSession.refund_amount)).where(ChatSession.outcome == "approve"))
        ).scalar() or 0.0
        customer_count = (await db.execute(select(func.count(Customer.customer_id)))).scalar()

    return {
        "total_sessions": total_sessions,
        "approved": approved,
        "denied": denied,
        "escalated": escalated,
        "pending": total_sessions - approved - denied - escalated,
        "total_refunded": round(total_refunded, 2),
        "customer_count": customer_count,
        "approval_rate": round(approved / total_sessions * 100, 1) if total_sessions else 0,
    }


@admin.get("/customers")
async def list_customers():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Customer).order_by(Customer.name))
        customers = result.scalars().all()

    return [
        {
            "customer_id": c.customer_id,
            "name": c.name,
            "email": c.email,
            "loyalty_tier": c.loyalty_tier,
            "fraud_flag": c.fraud_flag,
            "total_orders": c.total_orders,
            "total_spent": c.total_spent,
        }
        for c in customers
    ]


app.include_router(admin)


# ── Voice endpoint ────────────────────────────────────────────────────────────

_MULTIPART_OVERHEAD = 64 * 1024


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"Audio file too large (max {limit // (1024 * 1024)} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/voice/transcribe")
async def transcribe_audio(
    request: Request,
    file: Annotated[UploadFile, File()],
    transcribe: Annotated[Transcriber, Depends(get_transcriber)],
):
    """Transcribe a short voice clip (webm/ogg/mp4/mp3/wav) for the chat input."""
    limit = settings.max_audio_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + _MULTIPART_OVERHEAD:
        raise HTTPException(status_code=413, detail=f"Audio file too large (max {limit // (1024 * 1024)} MB)")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio format")

    audio = await _read_capped(file, limit)
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if sniff_audio(audio) is None:
        raise HTTPException(status_code=415, detail="File content is not a supported audio format")

    try:
        text = await transcribe(file.filename or "audio.webm", audio)
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail="Speech-to-text service failed") from exc
    return {"text": text.strip()}


# ── Health check ─────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ShopWave AI Refund Agent"}
