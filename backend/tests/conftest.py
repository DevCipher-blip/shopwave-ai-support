import os
import tempfile
from pathlib import Path

# Settings and the engine are created at import time, so configure them first.
_tmp = Path(tempfile.mkdtemp(prefix="shopwave-tests-"))
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp / 'test.db'}",
    LLM_PROVIDER="fake",
    STT_PROVIDER="fake",
    GROQ_API_KEY="",
    ADMIN_TOKEN="test-admin-token-0123456789",
    CORS_ORIGINS="http://localhost:3000",
)

import pytest  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from app.database.db import engine  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.database.seed import seed  # noqa: E402

ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]


async def reset_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await seed()


@pytest.fixture
async def db():
    await reset_database()
    yield
    await engine.dispose()


class ScriptedModel(GenericFakeChatModel):
    """Replays a fixed list of AIMessages, tool calls included."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages: AIMessage) -> ScriptedModel:
    return ScriptedModel(messages=iter(messages))


def tool_call(name: str, call_id: str = "call_1", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
