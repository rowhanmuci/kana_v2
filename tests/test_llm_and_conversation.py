from kana.config import Settings
from kana.domain.character import Character
from kana.domain.conversation import ConversationService, InboundMessage
from kana.domain.persona import PersonaPromptBuilder
from kana.infra.llm import FakeProvider, LLMClient
from kana.infra.repository import Repositories


def _client(handler):
    settings = Settings(_env_file=None)
    return LLMClient(settings, {"ollama": FakeProvider(handler)})


def _builder():
    return PersonaPromptBuilder(Character(
        id="t", name="測試角", core="測試核心人設", speech="測試說話方式", never="測試絕不清單",
    ))


def _msg(text: str) -> InboundMessage:
    return InboundMessage(channel="cli", sender_id="u1", display_name="小明", text=text)


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
    captured = {}

    def handler(**kw):
        captured.update(kw)
        return "喔，還好啦"

    repos = await Repositories.create(str(tmp_path / "c.db"), "t")
    try:
        convo = ConversationService(repos, _client(handler), _builder())
        reply = await convo.handle(_msg("妳今天好嗎"))
        assert reply == "喔，還好啦"

        # system prompt 來自注入的角色包，不是寫死的
        assert "測試核心人設" in captured["system"]
        assert "測試絕不清單" in captured["system"]

        # user_id 已加平台命名空間
        rel = await repos.relationship.get("cli:u1")
        assert rel is not None and rel.display_name == "小明"

        msgs = await repos.message.recent("cli:u1", limit=10)
        assert [(m.role, m.content) for m in msgs] == [
            ("user", "妳今天好嗎"),
            ("assistant", "喔，還好啦"),
        ]
    finally:
        await repos.close()


async def test_conversation_strips_timestamp_prefix(tmp_path):
    def handler(**kw):
        return "[2026-05-19 22:53] 在寫論文啊"

    repos = await Repositories.create(str(tmp_path / "c2.db"), "t")
    try:
        convo = ConversationService(repos, _client(handler), _builder())
        reply = await convo.handle(_msg("在幹嘛"))
        assert reply == "在寫論文啊"
    finally:
        await repos.close()
