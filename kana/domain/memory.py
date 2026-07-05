"""檢索式情節記憶：寫入時向量化，想起時三項加權。

評分公式（Generative Agents 的精神，權重收在 config）：
  score = w_rel · relevance(cosine 相似度)
        + w_rec · recency(半衰期指數衰減)
        + w_imp · importance(寫入時 LLM 打的 0..1)
        - 冷卻懲罰（剛想起過的事再想起要扣分——別每次都撈同一段回憶）

刻意不做的（baseline 先跑起來，見 REBUILD_PLAN §4）：re-ranker、query 改寫、MMR。
太新的記憶不撈：它們還在對話歷史視窗裡，重複注入只會佔 token。
sqlite-vec 不可用或 embedding 失敗時優雅退化：檢索退成 recency+importance，寫入照常。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..infra.embeddings import EmbeddingProvider
from ..infra.models import EpisodicMemory
from ..infra.repository import Repositories
from ..util import now_utc

logger = logging.getLogger("kana.memory")


@dataclass(frozen=True)
class RecallWeights:
    """三項加權＋冷卻。調權重是 Phase 2 的主要調校工作，全部可從 config 覆蓋。"""

    relevance: float = 0.55
    recency: float = 0.25
    importance: float = 0.20
    half_life_days: float = 3.0          # recency 半衰期：3 天前的記憶 recency 剩一半
    cooldown_hours: float = 6.0          # 剛想起過的冷卻時間
    cooldown_penalty: float = 0.3        # 冷卻期內再被撈到的扣分


def score_memory(
    mem: EpisodicMemory,
    similarity: float,
    now: datetime,
    w: RecallWeights,
) -> float:
    """單筆記憶的召回分數。純函式，可直接測。similarity ∈ [0,1]，無向量時傳 0。"""
    age_days = max(0.0, (now - mem.created_at).total_seconds() / 86400)
    recency = 0.5 ** (age_days / w.half_life_days)
    score = w.relevance * similarity + w.recency * recency + w.importance * mem.importance
    if mem.last_recalled_at is not None:
        if now - mem.last_recalled_at < timedelta(hours=w.cooldown_hours):
            score -= w.cooldown_penalty
    return score


class MemoryService:
    """remember（寫入＋向量化）與 recall（三項加權想起）。"""

    def __init__(
        self,
        repos: Repositories,
        embeddings: EmbeddingProvider | None,
        weights: RecallWeights = RecallWeights(),
        *,
        candidate_pool: int = 50,
        min_age_minutes: int = 90,
    ):
        self._repos = repos
        self._embeddings = embeddings
        self._w = weights
        self._pool = candidate_pool
        self._min_age = timedelta(minutes=min_age_minutes)

    @property
    def _vec_ready(self) -> bool:
        return self._embeddings is not None and self._repos.db.vec_enabled

    async def remember(
        self, kind: str, content: str, *,
        user_id: str | None = None, importance: float = 0.5,
    ) -> EpisodicMemory:
        """寫入記憶並向量化。embedding 失敗不影響寫入（之後仍可靠 recency 撈到）。"""
        mem = await self._repos.memory.add(kind, content, user_id=user_id, importance=importance)
        if self._vec_ready:
            try:
                vectors = await self._embeddings.embed([content])
                if vectors:
                    await self._repos.memory.set_vector(mem.id, vectors[0])
            except Exception as e:
                logger.warning("記憶向量化失敗（id=%s）：%s", mem.id, e)
        return mem

    async def recall(
        self, query: str, *, user_id: str | None = None, k: int = 5,
    ) -> list[EpisodicMemory]:
        """想起與 query 相關的舊事。

        範圍：她自己的記憶（user_id=NULL）＋與這個人的記憶——別人的對話不會洩漏過來。
        """
        now = now_utc()
        candidates: list[tuple[EpisodicMemory, float]] = []

        if self._vec_ready:
            try:
                vectors = await self._embeddings.embed([query])
                if vectors:
                    for mem, distance in await self._repos.memory.knn(vectors[0], self._pool):
                        candidates.append((mem, max(0.0, 1.0 - distance)))
            except Exception as e:
                logger.warning("向量檢索失敗，退化為 recency：%s", e)

        if not candidates:
            # 退化路徑：沒向量就拿最近的，similarity 全 0 → 純 recency+importance
            candidates = [(m, 0.0) for m in await self._repos.memory.recent(limit=self._pool)]

        scored = [
            (score_memory(mem, sim, now, self._w), mem)
            for mem, sim in candidates
            if (mem.user_id is None or mem.user_id == user_id)
            and (now - mem.created_at) >= self._min_age   # 太新的還在對話歷史裡
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        picked = [mem for _, mem in scored[:k]]

        if picked:
            await self._repos.memory.mark_recalled([m.id for m in picked])
        return picked
