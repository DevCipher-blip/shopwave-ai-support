"""Speech-to-text for the voice input: Groq Whisper, or a fixed fake for demos and tests."""

from collections.abc import Awaitable, Callable

from app.config import settings

Transcriber = Callable[[str, bytes], Awaitable[str]]

ALLOWED_AUDIO_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/x-m4a",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
    }
)

FAKE_TRANSCRIPT = "Hi, my order ORD-10015 arrived damaged and I would like a refund."


class TranscriptionError(Exception):
    pass


def sniff_audio(data: bytes) -> str | None:
    """Identify the container from magic bytes; the browser-sent MIME type is only a hint."""
    head = data[:16]
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


async def groq_transcribe(filename: str, data: bytes) -> str:
    import groq

    client = groq.AsyncGroq(api_key=settings.groq_api_key)
    try:
        transcription = await client.audio.transcriptions.create(
            file=(filename, data),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="en",
        )
    except groq.APIError as exc:
        raise TranscriptionError(str(exc)) from exc
    return transcription if isinstance(transcription, str) else transcription.text


async def fake_transcribe(filename: str, data: bytes) -> str:
    return FAKE_TRANSCRIPT


def get_transcriber() -> Transcriber:
    return fake_transcribe if settings.stt_provider == "fake" else groq_transcribe
