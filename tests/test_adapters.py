from kana.adapters.base import ChatAdapter
from kana.adapters.cli_adapter import CliAdapter
from kana.config import Settings
from kana.domain.character import Character
from kana.domain.conversation import ConversationService, InboundMessage
from kana.domain.pacing import ReplyPlan
from kana.domain.persona import PersonaPromptBuilder
from kana.infra.llm import FakeProvider, LLMClient
from kana.infra.repository import Repositories


async def test_cli_adapter_roundtrip(monkeypatch, capsys):
    inputs = iter(["哈囉", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    received: list[InboundMessage] = []

    async def handler(msg: InboundMessage) -> ReplyPlan:
        received.append(msg)
        return ReplyPlan(parts=["嗨", "怎麼了"], gaps=[0.0])

    adapter = CliAdapter()
    assert isinstance(adapter, ChatAdapter)
    await adapter.run(handler)

    assert len(received) == 1
    assert received[0].channel == "cli"
    assert received[0].sender_id == "local"
    assert received[0].text == "哈囉"
    out = capsys.readouterr().out
    assert "嗨" in out and "怎麼了" in out  # 多條 parts 都有印出


async def test_user_id_namespacing_no_collision(tmp_path):
    """同一個平台原生 id、不同通道 → DB 內是兩個不同使用者。"""
    def handler(**kw):
        if kw.get("fmt"):
            return '{"summary": "", "familiarity_delta": 0, "affection_delta": 0, ' \
                   '"new_known_facts": [], "new_inside_jokes": [], "mood_toward_user": "neutral"}'
        return "好"

    repos = await Repositories.create(str(tmp_path / "ns.db"), "t")
    builder = PersonaPromptBuilder(Character(
        id="t", name="測試角", core="核", speech="說", never="絕",
    ))
    llm = LLMClient(Settings(_env_file=None), {"ollama": FakeProvider(handler)})
    convo = ConversationService(repos, llm, builder, pacing_scale=0.0)
    try:
        await convo.handle(InboundMessage(
            channel="cli", sender_id="42", display_name="CLI的人", text="hi"))
        await convo.handle(InboundMessage(
            channel="discord", sender_id="42", display_name="DC的人", text="hi"))
        await convo.drain()

        rel_cli = await repos.relationship.get("cli:42")
        rel_dc = await repos.relationship.get("discord:42")
        assert rel_cli is not None and rel_cli.display_name == "CLI的人"
        assert rel_dc is not None and rel_dc.display_name == "DC的人"

        # 訊息也各自獨立
        assert len(await repos.message.recent("cli:42")) == 2      # user + assistant
        assert len(await repos.message.recent("discord:42")) == 2
    finally:
        await repos.close()
