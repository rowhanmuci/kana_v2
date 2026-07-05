import json

from kana.config import Settings
from kana.domain.relationship import EvolutionResult, RelationshipEvolver, calc_stage
from kana.infra.llm import FakeProvider, LLMClient
from kana.infra.repository import Repositories


def _llm(payload: dict) -> LLMClient:
    def handler(**kw):
        return json.dumps(payload, ensure_ascii=False)
    return LLMClient(Settings(_env_file=None), {"ollama": FakeProvider(handler)})


# ── calc_stage 門檻 ──

def test_stage_thresholds():
    assert calc_stage(0, 0) == "stranger"
    assert calc_stage(15, 0) == "acquaintance"
    assert calc_stage(40, 40) == "friend"
    assert calc_stage(70, 80) == "close"
    assert calc_stage(150, 150) == "special"


# ── EvolutionResult 淨化層（v1 死因的直接對策）──

def test_dirty_list_items_sanitized():
    """list 混入 dict：字串 dict 取 content、其他丟棄——v1 就是這個炸掉的。"""
    r = EvolutionResult(new_known_facts=[
        "他剛植牙",
        {"content": "吃使用者的藥副作用是直接休學"},   # v1 DB 裡真實的髒資料形狀
        {"weird": "no content"},
        123,
        "  ",
    ])
    assert r.new_known_facts == ["他剛植牙", "吃使用者的藥副作用是直接休學"]


def test_deltas_clamped():
    r = EvolutionResult(familiarity_delta=99, affection_delta=-99, importance=3.0)
    assert r.familiarity_delta == 10
    assert r.affection_delta == -10
    assert r.importance == 1.0


# ── evolve 全流程 ──

async def test_evolve_updates_relationship_and_memory(tmp_path):
    repos = await Repositories.create(str(tmp_path / "e.db"), "t")
    try:
        await repos.relationship.ensure("cli:u1", "小明")
        llm = _llm({
            "summary": "聊了他的貓",
            "emotional_moment": None,
            "importance": 0.5,
            "familiarity_delta": 3,
            "affection_delta": 5,
            "new_known_facts": ["他養了一隻叫麻糬的貓"],
            "new_inside_jokes": [],
            "mood_toward_user": "warm",
        })
        await RelationshipEvolver(repos, llm).evolve("cli:u1", "我家貓叫麻糬", "麻糬 這名字很好")

        rel = await repos.relationship.get("cli:u1")
        assert rel.familiarity == 3
        assert rel.affection == 5
        assert rel.relationship_stage == "acquaintance"
        assert rel.known_facts == ["他養了一隻叫麻糬的貓"]
        assert rel.last_mood_toward == "warm"

        mems = await repos.memory.recent(kind="conversation")
        assert len(mems) == 1
        assert mems[0].content == "聊了他的貓"
        assert mems[0].user_id == "cli:u1"
        assert mems[0].importance == 0.5
    finally:
        await repos.close()


async def test_evolve_dedupes_and_caps_facts(tmp_path):
    repos = await Repositories.create(str(tmp_path / "e2.db"), "t")
    try:
        await repos.relationship.ensure("cli:u1", "小明")
        await repos.relationship.update(
            "cli:u1", known_facts=[f"舊事實{i}" for i in range(29)] + ["他剛植牙"])
        llm = _llm({
            "summary": "又聊到植牙",
            "familiarity_delta": 1, "affection_delta": 0,
            "new_known_facts": ["他剛植牙", "他這週去高雄"],  # 一條重複、一條新
            "new_inside_jokes": [],
            "mood_toward_user": "neutral",
        })
        await RelationshipEvolver(repos, llm).evolve("cli:u1", "x", "y")

        rel = await repos.relationship.get("cli:u1")
        assert len(rel.known_facts) == 30            # cap 生效
        assert rel.known_facts[-1] == "他這週去高雄"  # 新的進來
        assert rel.known_facts.count("他剛植牙") == 1  # 去重
        assert "舊事實0" not in rel.known_facts       # 最舊的被遺忘
    finally:
        await repos.close()


async def test_evolve_emotional_moment_raises_importance(tmp_path):
    repos = await Repositories.create(str(tmp_path / "e3.db"), "t")
    try:
        await repos.relationship.ensure("cli:u1", "小明")
        llm = _llm({
            "summary": "他說了很重要的事",
            "emotional_moment": "第一次聊到家人",
            "importance": 0.3,
            "familiarity_delta": 4, "affection_delta": 6,
            "new_known_facts": [], "new_inside_jokes": [],
            "mood_toward_user": "warm",
        })
        await RelationshipEvolver(repos, llm).evolve("cli:u1", "x", "y")
        mems = await repos.memory.recent(kind="conversation")
        assert mems[0].importance == 0.7  # 情感時刻墊高
    finally:
        await repos.close()


async def test_evolve_bad_json_is_noop(tmp_path):
    """LLM 回垃圾 → 記 log 跳過，關係不動、不炸。"""
    def handler(**kw):
        return "我覺得這次對話很棒！"

    repos = await Repositories.create(str(tmp_path / "e4.db"), "t")
    try:
        await repos.relationship.ensure("cli:u1", "小明")
        llm = LLMClient(Settings(_env_file=None), {"ollama": FakeProvider(handler)})
        await RelationshipEvolver(repos, llm).evolve("cli:u1", "x", "y")

        rel = await repos.relationship.get("cli:u1")
        assert rel.familiarity == 0 and rel.known_facts == []
        assert await repos.memory.recent(kind="conversation") == []
    finally:
        await repos.close()
