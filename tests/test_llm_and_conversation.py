import json

from kana.config import Settings
from kana.infra.llm import FakeProvider, LLMClient
from kana.infra.repository import Repositories
from kana.domain.conversation import ConversationService


def _client(handler):
    settings = Settings(_env_file=None)
    return LLMClient(settings, {"ollama": FakeProvider(handler)})


async def test_llm_routing_passes_model_and_tokens():
    captured = {}

    def handler(**kw):
        captured.update(kw)
        return "ok"

    client = _client(handler)
    out = await client.chat("chat", messages=[{"role": "user", "content": "hi"}], system="sys")
    assert out == "ok"
    assert captured["model"] == "qwen3:14b"
    assert captured["max_tokens"] == 500
    assert captured["system"] == "sys"


async def test_chat_json_parses_fenced():
    def handler(**kw):
        return "```json\n{\"a\": 1, \"b\": [1, 2,]}\n```"

    client = _client(handler)
    data = await client.chat_json("memory", messages=[{"role": "user", "content": "x"}])
    assert data == {"a": 1, "b": [1, 2]}


async def test_conversation_roundtrip(tmp_path):
    def handler(**kw):
        return "喔，還好啦"

    repos = await Repositories.create(str(tmp_path / "c.db"))
    try:
        convo = ConversationService(repos, _client(handler))
        reply = await convo.handle("u1", "小明", "妳今天好嗎")
        assert reply == "喔，還好啦"

        rel = await repos.relationship.get("u1")
        assert rel is not None and rel.display_name == "小明"

        msgs = await repos.message.recent("u1", limit=10)
        assert [(m.role, m.content) for m in msgs] == [
            ("user", "妳今天好嗎"),
            ("assistant", "喔，還好啦"),
        ]
    finally:
        await repos.close()


async def test_conversation_strips_timestamp_prefix(tmp_path):
    def handler(**kw):
        return "[2026-05-19 22:53] 在寫論文啊"

    repos = await Repositories.create(str(tmp_path / "c2.db"))
    try:
        convo = ConversationService(repos, _client(handler))
        reply = await convo.handle("u1", "小明", "在幹嘛")
        assert reply == "在寫論文啊"
    finally:
        await repos.close()
