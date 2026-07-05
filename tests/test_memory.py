from datetime import timedelta

from kana.domain.memory import MemoryService, RecallWeights, score_memory
from kana.infra.embeddings import FakeEmbeddingProvider
from kana.infra.models import EpisodicMemory
from kana.infra.repository import Repositories
from kana.util import now_utc, to_iso

_W = RecallWeights()

# 4 維假向量：貓 / 論文 / 音樂 各佔一軸，fallback 佔第四軸
_CAT = [1.0, 0.0, 0.0, 0.0]
_THESIS = [0.0, 1.0, 0.0, 0.0]
_MUSIC = [0.0, 0.0, 1.0, 0.0]
_OTHER = [0.0, 0.0, 0.0, 1.0]

_EMBED = FakeEmbeddingProvider({"貓": _CAT, "論文": _THESIS, "音樂": _MUSIC}, _OTHER)


def _mem(**kw) -> EpisodicMemory:
    base = dict(character_id="t", kind="conversation", content="x", importance=0.5)
    base.update(kw)
    return EpisodicMemory(**base)


async def _backdate(repos: Repositories, memory_id: int, days: float) -> None:
    """測試用：把記憶的建立時間往回撥（repo 寫入時一律用現在時間）。"""
    await repos.db.execute(
        "UPDATE memory_episodic SET created_at = ? WHERE id = ?",
        (to_iso(now_utc() - timedelta(days=days)), memory_id),
    )


def _service(repos, *, min_age=0, weights=_W, embed=_EMBED) -> MemoryService:
    return MemoryService(repos, embed, weights, min_age_minutes=min_age)


# ── score_memory 純函式 ──

def test_score_relevance_dominates():
    now = now_utc()
    old_relevant = _mem(created_at=now - timedelta(days=10))
    fresh_irrelevant = _mem(created_at=now)
    assert score_memory(old_relevant, 1.0, now, _W) > score_memory(fresh_irrelevant, 0.0, now, _W)


def test_score_recency_halves_at_half_life():
    now = now_utc()
    fresh = score_memory(_mem(created_at=now), 0.0, now, _W)
    aged = score_memory(_mem(created_at=now - timedelta(days=_W.half_life_days)), 0.0, now, _W)
    # 相差 = w_rec 的一半
    assert abs((fresh - aged) - _W.recency / 2) < 1e-9


def test_score_importance_contributes():
    now = now_utc()
    dull = _mem(created_at=now, importance=0.1)
    vivid = _mem(created_at=now, importance=0.9)
    assert score_memory(vivid, 0.0, now, _W) > score_memory(dull, 0.0, now, _W)


def test_score_cooldown_penalty():
    now = now_utc()
    just_recalled = _mem(created_at=now, last_recalled_at=now - timedelta(hours=1))
    long_ago_recalled = _mem(created_at=now, last_recalled_at=now - timedelta(hours=24))
    assert score_memory(long_ago_recalled, 0.5, now, _W) - \
           score_memory(just_recalled, 0.5, now, _W) == _W.cooldown_penalty


# ── recall 整合（真 sqlite-vec + 假向量）──

async def test_recall_by_relevance(tmp_path):
    repos = await Repositories.create(str(tmp_path / "m.db"), "t", embedding_dim=4)
    try:
        svc = _service(repos)
        m1 = await svc.remember("conversation", "他養了一隻貓叫麻糬", user_id="cli:u1")
        m2 = await svc.remember("conversation", "他論文卡在第三章", user_id="cli:u1")
        await _backdate(repos, m1.id, 5)   # 貓的記憶比較舊
        await _backdate(repos, m2.id, 1)

        picked = await svc.recall("欸 我家貓今天很吵", user_id="cli:u1", k=1)
        assert len(picked) == 1
        assert "麻糬" in picked[0].content   # 雖然比較舊，相關性贏過 recency
    finally:
        await repos.close()


async def test_recall_scopes_to_user_and_self(tmp_path):
    repos = await Repositories.create(str(tmp_path / "m2.db"), "t", embedding_dim=4)
    try:
        svc = _service(repos)
        other = await svc.remember("conversation", "u2 說他討厭貓", user_id="cli:u2")
        mine = await svc.remember("conversation", "u1 家的貓叫麻糬", user_id="cli:u1")
        hers = await svc.remember("self", "今天看到一隻很像麻糬的貓", user_id=None)
        for m in (other, mine, hers):
            await _backdate(repos, m.id, 1)

        picked = await svc.recall("貓", user_id="cli:u1", k=5)
        contents = [m.content for m in picked]
        assert any("麻糬" in c for c in contents)
        assert all("u2" not in c for c in contents)   # 別人的對話不洩漏
    finally:
        await repos.close()


async def test_recall_min_age_excludes_fresh(tmp_path):
    repos = await Repositories.create(str(tmp_path / "m3.db"), "t", embedding_dim=4)
    try:
        svc = _service(repos, min_age=90)
        await svc.remember("conversation", "剛剛才聊到貓", user_id="cli:u1")
        assert await svc.recall("貓", user_id="cli:u1") == []   # 還在對話歷史裡，不撈
    finally:
        await repos.close()


async def test_recall_marks_and_cools_down(tmp_path):
    repos = await Repositories.create(str(tmp_path / "m4.db"), "t", embedding_dim=4)
    try:
        # 高懲罰讓效果明顯：第一次想起貓之後，第二次換論文的記憶上位
        w = RecallWeights(cooldown_penalty=10.0)
        svc = _service(repos, weights=w)
        m_cat = await svc.remember("conversation", "他家的貓叫麻糬", user_id="cli:u1")
        m_th = await svc.remember("conversation", "音樂品味聊得來", user_id="cli:u1")
        await _backdate(repos, m_cat.id, 1)
        await _backdate(repos, m_th.id, 1)

        first = await svc.recall("貓", user_id="cli:u1", k=1)
        assert "麻糬" in first[0].content

        second = await svc.recall("貓", user_id="cli:u1", k=1)
        assert "麻糬" not in second[0].content   # 冷卻中，換別的
    finally:
        await repos.close()


async def test_recall_fallback_without_embeddings(tmp_path):
    """沒有 embedding provider → 退化為 recency+importance，不炸。"""
    repos = await Repositories.create(str(tmp_path / "m5.db"), "t", embedding_dim=4)
    try:
        svc = MemoryService(repos, None, _W, min_age_minutes=0)
        m_old = await svc.remember("self", "上週的事", user_id=None)
        m_new = await svc.remember("self", "昨天的事", user_id=None)
        await _backdate(repos, m_old.id, 7)
        await _backdate(repos, m_new.id, 1)

        picked = await svc.recall("隨便什麼", user_id="cli:u1", k=1)
        assert picked[0].content == "昨天的事"
    finally:
        await repos.close()
