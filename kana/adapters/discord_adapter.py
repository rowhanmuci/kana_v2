"""Discord adapter（薄 I/O）：收發 + 節奏執行，不含 domain 決策。

實作 ChatAdapter。Phase 1 行為：
  - 緩衝合併：使用者連發訊息時，等一個靜默窗口（domain 的 buffer_window 決定）
    再合併成一則交給 handler——像真人不會對每一句分開回。
  - 節奏執行：照 ReplyPlan 先等 initial_delay（期間不 typing，像還沒看到），
    要送出前才顯示 typing，多條之間隔 gaps。
管理員頻道、非 DM 留給之後的 phase。
"""

from __future__ import annotations

import asyncio
import logging

import discord

from .base import MessageHandler
from ..domain.conversation import InboundMessage
from ..domain.pacing import ReplyPlan, buffer_window

logger = logging.getLogger("kana.discord")


class DiscordAdapter:
    name = "discord"

    def __init__(self, token: str):
        self._token = token
        self._handler: MessageHandler | None = None
        # 每個使用者一個緩衝：累積的訊息 + 等待中的 debounce task
        self._buffers: dict[int, list[discord.Message]] = {}
        self._pending: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info("上線：%s (ID: %s)", self._client.user, self._client.user.id)

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author == self._client.user:
                return
            if not isinstance(message.channel, discord.DMChannel):
                return  # 目前只回 DM
            if self._handler is None:
                return
            self._enqueue(message)

    def _enqueue(self, message: discord.Message) -> None:
        """緩衝合併：重置該使用者的靜默計時，窗口內的連發會合併處理。"""
        author_id = message.author.id
        self._buffers.setdefault(author_id, []).append(message)
        logger.info("收到 DM（入緩衝）：sender=%s content=%s", author_id, message.content[:50])

        old = self._pending.pop(author_id, None)
        if old is not None:
            old.cancel()
        self._pending[author_id] = asyncio.create_task(self._flush_later(author_id))

    async def _flush_later(self, author_id: int) -> None:
        try:
            await asyncio.sleep(buffer_window())
        except asyncio.CancelledError:
            return  # 又來了新訊息，由新的 task 接手
        self._pending.pop(author_id, None)

        batch = self._buffers.pop(author_id, [])
        if not batch:
            return
        last = batch[-1]
        msg = InboundMessage(
            channel=self.name,
            sender_id=str(author_id),
            display_name=last.author.display_name or last.author.name,
            text="\n".join(m.content for m in batch if m.content),
        )

        try:
            plan = await self._handler(msg)
            await self._deliver(last.channel, plan)
        except Exception:
            logger.exception("處理訊息失敗：sender=%s", author_id)

    async def _deliver(self, channel: discord.abc.Messageable, plan: ReplyPlan) -> None:
        """照 ReplyPlan 的節奏送出：延遲期間安靜，要送前才 typing。"""
        if plan.is_empty:
            return
        if plan.initial_delay > 0:
            await asyncio.sleep(plan.initial_delay)
        for i, part in enumerate(plan.parts):
            if i > 0:
                await asyncio.sleep(plan.gaps[i - 1] if i - 1 < len(plan.gaps) else 2.0)
            try:
                async with channel.typing():
                    await asyncio.sleep(min(len(part) / 6.0, 5.0))  # 短暫的打字感
                await channel.send(part)
            except discord.HTTPException:
                logger.exception("送出失敗，跳過此 part")

    async def run(self, on_message: MessageHandler) -> None:
        self._handler = on_message
        await self._client.start(self._token)

    async def send(self, recipient_id: str, text: str) -> None:
        user = await self._client.fetch_user(int(recipient_id))
        await user.send(text)

    async def close(self) -> None:
        for task in self._pending.values():
            task.cancel()
        await self._client.close()
