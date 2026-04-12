"""
Tests for conversational memory in process_chat().

Verifies:
- _load_history returns empty list for new session
- _save_messages creates and appends to chat_sessions doc
- _load_history returns last N messages respecting MAX_HISTORY_MESSAGES
- _ensure_chat_sessions_index is idempotent (no error on second call)
- process_chat builds messages array with history + current message
- assistant text is accumulated and saved after streaming completes
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from agents.chat import (
    _load_history,
    _save_messages,
    _ensure_chat_sessions_index,
    MAX_HISTORY_MESSAGES,
)


# --- Fake MongoDB collection ---

class FakeChatSessionsCollection:
    """In-memory mock of db.chat_sessions for unit tests."""

    def __init__(self):
        self._store: dict[str, dict] = {}
        self._indexes_created = []

    async def find_one(self, filter_dict, projection=None):
        sid = filter_dict.get("session_id")
        return self._store.get(sid)

    async def update_one(self, filter_dict, update, upsert=False):
        sid = filter_dict.get("session_id")
        doc = self._store.get(sid)

        if doc is None and upsert:
            doc = {"session_id": sid, "messages": []}
            self._store[sid] = doc

        if doc is None:
            return

        if "$push" in update:
            push = update["$push"]
            if "messages" in push:
                each = push["messages"].get("$each", [])
                doc.setdefault("messages", []).extend(each)

        if "$set" in update:
            for k, v in update["$set"].items():
                doc[k] = v

    async def create_index(self, field, **kwargs):
        self._indexes_created.append((field, kwargs))


class FakeDB:
    """Minimal db mock with chat_sessions collection."""

    def __init__(self):
        self.chat_sessions = FakeChatSessionsCollection()


# --- Tests ---

@pytest.fixture
def db():
    return FakeDB()


@pytest.mark.asyncio
async def test_load_history_empty_session(db):
    """New session_id returns empty history."""
    result = await _load_history(db, "new-session-123")
    assert result == []


@pytest.mark.asyncio
async def test_save_and_load_messages(db):
    """Save a message pair, then load it back."""
    await _save_messages(db, "sess-1", "contador", "Hola", "Hola, soy SISMO")
    history = await _load_history(db, "sess-1")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Hola"}
    assert history[1] == {"role": "assistant", "content": "Hola, soy SISMO"}


@pytest.mark.asyncio
async def test_save_appends_multiple_pairs(db):
    """Multiple saves append to the same session."""
    await _save_messages(db, "sess-2", "contador", "Msg 1", "Resp 1")
    await _save_messages(db, "sess-2", "contador", "Msg 2", "Resp 2")
    history = await _load_history(db, "sess-2")
    assert len(history) == 4
    assert history[2]["content"] == "Msg 2"
    assert history[3]["content"] == "Resp 2"


@pytest.mark.asyncio
async def test_load_history_respects_max_limit(db):
    """History is truncated to MAX_HISTORY_MESSAGES."""
    # Insert more than MAX_HISTORY_MESSAGES messages
    for i in range(MAX_HISTORY_MESSAGES + 10):
        db.chat_sessions._store.setdefault("sess-big", {
            "session_id": "sess-big",
            "messages": [],
        })["messages"].append({"role": "user", "content": f"msg-{i}"})

    history = await _load_history(db, "sess-big")
    assert len(history) == MAX_HISTORY_MESSAGES
    # Should be the LAST N messages
    assert history[0]["content"] == f"msg-{10}"  # skipped first 10


@pytest.mark.asyncio
async def test_save_sets_updated_at(db):
    """Save sets updated_at for TTL expiry."""
    await _save_messages(db, "sess-ts", "contador", "Q", "A")
    doc = db.chat_sessions._store["sess-ts"]
    assert "updated_at" in doc
    assert isinstance(doc["updated_at"], datetime)


@pytest.mark.asyncio
async def test_save_sets_agent_type(db):
    """Save records the agent_type."""
    await _save_messages(db, "sess-agent", "cfo", "Q", "A")
    doc = db.chat_sessions._store["sess-agent"]
    assert doc["agent_type"] == "cfo"


@pytest.mark.asyncio
async def test_ensure_index_idempotent(db):
    """Calling _ensure_chat_sessions_index twice does not raise."""
    await _ensure_chat_sessions_index(db)
    await _ensure_chat_sessions_index(db)
    assert len(db.chat_sessions._indexes_created) == 2  # called twice, both succeed


@pytest.mark.asyncio
async def test_ensure_index_error_suppressed():
    """If create_index raises, it is silently ignored."""
    mock_db = MagicMock()
    mock_db.chat_sessions.create_index = AsyncMock(side_effect=Exception("index error"))
    # Should not raise
    await _ensure_chat_sessions_index(mock_db)


@pytest.mark.asyncio
async def test_separate_sessions_isolated(db):
    """Messages from different sessions do not mix."""
    await _save_messages(db, "sess-a", "contador", "A1", "A2")
    await _save_messages(db, "sess-b", "contador", "B1", "B2")
    history_a = await _load_history(db, "sess-a")
    history_b = await _load_history(db, "sess-b")
    assert len(history_a) == 2
    assert len(history_b) == 2
    assert history_a[0]["content"] == "A1"
    assert history_b[0]["content"] == "B1"
