"""對話流程（單一垂直切片）。

round-trip：命名空間化 user_id → 存訊息 → 組 prompt → LLM → 存回覆 → touch 關係。
全程走型別層，不碰 SQL。延遲邏輯、記憶檢索、關係演化留給 Phase 1+。

InboundMessage 是通道無關的入站訊息 DTO：adapter 把平台事件轉成它，
domain 在 handle() 裡用 user_key() 加上平台命名空間——
adapter 永遠只碰平台原生 id，組合規則只存在這一處。
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from ..infra.llm import LLMClient
from ..infra.repository import Repositories
from ..util import user_key
from .persona import PersonaPromptBuilder

logger = logging.getLogger("kana.conversation")

_TS_PREFIX = re.compile(r"^\[?\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]?\s*")


class InboundMessage(BaseModel):
    """通道無關的入站訊息。sender_id 是平台原生 id（未加命名空間）。"""

    channel: str
    sender_id: str
    display_name: str
    text: str


class ConversationService:
    def __init__(self, repos: Repositories, llm: LLMClient,
                 persona: PersonaPromptBuilder, history_limit: int = 10):
        self._repos = repos
        self._llm = llm
        self._persona = persona
        self._history_limit = history_limit

    async def handle(self, msg: InboundMessage) -> str:
        uid = user_key(msg.channel, msg.sender_id)
        rel = await self._repos.relationship.ensure(uid, msg.display_name)
        await self._repos.message.add(uid, "user", msg.text)

        state = await self._repos.persona.get()
        history = await self._repos.message.recent(uid, limit=self._history_limit)
        messages = [{"role": m.role, "content": m.content} for m in history]

        system = self._persona.build(state, rel)
        try:
            reply = await self._llm.chat("chat", messages=messages, system=system)
        except Exception as e:
            logger.error("LLM 呼叫失敗：user=%s error=%s", uid, e)
            return ""

        reply = _TS_PREFIX.sub("", reply.strip()).strip()
        if not reply:
            logger.warning("空回覆：user=%s", uid)
            return ""

        await self._repos.message.add(uid, "assistant", reply)
        await self._repos.relationship.touch(uid)
        logger.info("回覆 user=%s：%s", uid, reply[:50])
        return reply
