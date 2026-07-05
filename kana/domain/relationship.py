"""關係演化：對話後抽取 known_facts / 熟悉度 / 好感度並更新關係。

v1 的停擺死因就在這條路上：LLM 回傳的 JSON 陣列混入 dict、直接存進 DB，
之後每次組 prompt join() 必炸。所以這層的原則是**寫入端強制淨化**：
LLM 輸出先過 Ollama 的 JSON schema（結構化輸出），再過 Pydantic 驗證，
list 欄位逐項強制轉字串、delta 夾在範圍內——髒資料進不了 DB。

v1 的承諾抽取（todo_commitments）實測效果不好，v2 不做。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, field_validator

from ..infra.llm import LLMClient
from ..infra.repository import Repositories

logger = logging.getLogger("kana.relationship")

_FACTS_CAP = 30     # known_facts 只留最新 N 條（遺忘是 feature）
_JOKES_CAP = 15

# Ollama 結構化輸出用的 JSON schema：從源頭擋掉型別漂移
_EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "emotional_moment": {"type": ["string", "null"]},
        "importance": {"type": "number"},
        "familiarity_delta": {"type": "integer"},
        "affection_delta": {"type": "integer"},
        "new_known_facts": {"type": "array", "items": {"type": "string"}},
        "new_inside_jokes": {"type": "array", "items": {"type": "string"}},
        "mood_toward_user": {
            "type": "string",
            "enum": ["neutral", "warm", "curious", "flustered", "annoyed", "distant"],
        },
    },
    "required": ["summary", "familiarity_delta", "affection_delta",
                 "new_known_facts", "new_inside_jokes", "mood_toward_user"],
}

_EVAL_SYSTEM = "你是一個分析對話的系統。只輸出符合 schema 的 JSON。"

_EVAL_PROMPT = """根據以下對話評估關係變化，輸出 JSON：
- summary：這次對話摘要（50 字以內，繁體中文）
- emotional_moment：有無特別的情感時刻（沒有填 null）
- importance：這次對話值得記住的程度 0~1（日常寒暄 0.2、聊到在乎的事 0.5、重要的情感事件 0.8+）
- familiarity_delta：-5 到 +10（正常聊天 +1~+3，深入交流 +4 以上）
- affection_delta：-10 到 +15（對方讓角色不舒服才是負的）
- new_known_facts：「使用者」這次透露的、關於**他自己**的新事實（每條一句話字串）。
  判斷原則：主詞必須是使用者。角色自己說的事（角色的家鄉、室友、論文等）一律不記。
  使用者只是提問、沒透露自己的事 → 填 []
- new_inside_jokes：這次對話產生的、兩人之間的梗（字串；很少發生，通常填 []）
- mood_toward_user：角色現在對這個人的心情

使用者說：{user_text}
角色回應：{reply_text}"""


def calc_stage(familiarity: int, affection: int) -> str:
    """關係階段門檻（沿用 v1 實測值）。"""
    if affection > 100 and familiarity > 100:
        return "special"
    if affection > 70 and familiarity > 60:
        return "close"
    if affection > 30 and familiarity > 30:
        return "friend"
    if affection > 0 or familiarity > 10:
        return "acquaintance"
    return "stranger"


class EvolutionResult(BaseModel):
    """LLM 抽取結果的淨化層：list 逐項轉純字串、delta 夾範圍。"""

    summary: str = ""
    emotional_moment: str | None = None
    importance: float = 0.4
    familiarity_delta: int = 0
    affection_delta: int = 0
    new_known_facts: list[str] = []
    new_inside_jokes: list[str] = []
    mood_toward_user: str = "neutral"

    @field_validator("new_known_facts", "new_inside_jokes", mode="before")
    @classmethod
    def _coerce_str_items(cls, v):
        """v1 的死因：list 混入 dict。逐項淨化：dict 取 content、其他非字串丟棄。"""
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                s = item["content"].strip()
            else:
                continue
            if s:
                out.append(s)
        return out

    @field_validator("familiarity_delta", mode="after")
    @classmethod
    def _clamp_fam(cls, v: int) -> int:
        return max(-5, min(10, v))

    @field_validator("affection_delta", mode="after")
    @classmethod
    def _clamp_aff(cls, v: int) -> int:
        return max(-10, min(15, v))

    @field_validator("importance", mode="after")
    @classmethod
    def _clamp_imp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class RelationshipEvolver:
    """對話後跑一次抽取＋更新。失敗只記 log，不影響對話主流程。

    對話摘要經 MemoryService 寫入（會向量化，Phase 2 檢索用）；
    沒給 memory 時退回直接寫 repo（無向量，仍可靠 recency 撈到）。
    """

    def __init__(self, repos: Repositories, llm: LLMClient, memory=None):
        self._repos = repos
        self._llm = llm
        self._memory = memory

    async def evolve(self, user_id: str, user_text: str, reply_text: str) -> None:
        try:
            raw = await self._llm.chat_json(
                "memory",
                messages=[{"role": "user", "content": _EVAL_PROMPT.format(
                    user_text=user_text, reply_text=reply_text)}],
                system=_EVAL_SYSTEM,
                schema=_EVAL_SCHEMA,
            )
            result = EvolutionResult(**raw)
        except Exception as e:
            logger.error("關係抽取失敗：user=%s error=%s", user_id, e)
            return

        rel = await self._repos.relationship.get(user_id)
        if rel is None:
            logger.warning("關係不存在，跳過演化：user=%s", user_id)
            return

        familiarity = max(0, min(1000, rel.familiarity + result.familiarity_delta))
        affection = max(-500, min(1000, rel.affection + result.affection_delta))

        # 去重後只留最新 N 條：無限堆積會把 prompt 撐爆，也不像人
        facts = list(dict.fromkeys(rel.known_facts + result.new_known_facts))[-_FACTS_CAP:]
        jokes = list(dict.fromkeys(rel.inside_jokes + result.new_inside_jokes))[-_JOKES_CAP:]

        await self._repos.relationship.update(
            user_id,
            familiarity=familiarity,
            affection=affection,
            relationship_stage=calc_stage(familiarity, affection),
            known_facts=facts,
            inside_jokes=jokes,
            last_mood_toward=result.mood_toward_user,
        )

        # 對話摘要進 episodic memory（帶向量），檢索資料持續累積
        if result.summary:
            importance = result.importance
            if result.emotional_moment:
                importance = max(importance, 0.7)
            if self._memory is not None:
                await self._memory.remember(
                    "conversation", result.summary, user_id=user_id, importance=importance)
            else:
                await self._repos.memory.add(
                    "conversation", result.summary, user_id=user_id, importance=importance)

        logger.info(
            "關係演化：user=%s fam=%+d aff=%+d stage=%s facts+%d",
            user_id, result.familiarity_delta, result.affection_delta,
            calc_stage(familiarity, affection), len(result.new_known_facts),
        )
