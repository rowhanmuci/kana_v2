"""對話流程（Phase 0 最小垂直切片）。

DM round-trip：存使用者訊息 → 組 prompt → LLM → 存回覆 → 更新關係。
全程走型別層，不碰 SQL。延遲邏輯、記憶檢索、關係更新留給 Phase 1+。
"""

from __future__ import annotations

import logging
import re

from ..infra.llm import LLMClient
from ..infra.repository import Repositories
from .persona import build_system_prompt

logger = logging.getLogger("kana.conversation")

_TS_PREFIX = re.compile(r"^\[?\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]?\s*")


class ConversationService:
    def __init__(self, repos: Repositories, llm: LLMClient, history_limit: int = 10):
        self._repos = repos
        self._llm = llm
        self._history_limit = history_limit

    async def handle(self, user_id: str, display_name: str, text: str) -> str:
        rel = await self._repos.relationship.ensure(user_id, display_name)
        await self._repos.message.add(user_id, "user", text)

        state = await self._repos.persona.get()
        history = await self._repos.message.recent(user_id, limit=self._history_limit)
        messages = [{"role": m.role, "content": m.content} for m in history]

        system = build_system_prompt(state, rel)
        try:
            reply = await self._llm.chat("chat", messages=messages, system=system)
        except Exception as e:
            logger.error("LLM 呼叫失敗：user=%s error=%s", user_id, e)
            return ""

        reply = _TS_PREFIX.sub("", reply.strip()).strip()
        if not reply:
            logger.warning("空回覆：user=%s", user_id)
            return ""

        await self._repos.message.add(user_id, "assistant", reply)
        await self._repos.relationship.touch(user_id)
        logger.info("回覆 user=%s：%s", user_id, reply[:50])
        return reply
