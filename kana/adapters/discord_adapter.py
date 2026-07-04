"""Discord adapter（薄 I/O）：只負責收發，不含任何 domain 邏輯。

實作 ChatAdapter。Phase 0.5 只處理 DM round-trip；
延遲、緩衝合併、管理員頻道留給 Phase 1+。
"""

from __future__ import annotations

import logging

import discord

from .base import MessageHandler
from ..domain.conversation import InboundMessage

logger = logging.getLogger("kana.discord")


class DiscordAdapter:
    name = "discord"

    def __init__(self, token: str):
        self._token = token
        self._handler: MessageHandler | None = None

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
                return  # Phase 0.5 只回 DM
            if self._handler is None:
                return

            msg = InboundMessage(
                channel=self.name,
                sender_id=str(message.author.id),
                display_name=message.author.display_name or message.author.name,
                text=message.content,
            )
            logger.info("收到 DM：sender=%s content=%s", msg.sender_id, msg.text[:50])

            try:
                async with message.channel.typing():
                    reply = await self._handler(msg)
            except discord.HTTPException:
                reply = await self._handler(msg)

            if reply:
                await message.channel.send(reply)

    async def run(self, on_message: MessageHandler) -> None:
        self._handler = on_message
        await self._client.start(self._token)

    async def send(self, recipient_id: str, text: str) -> None:
        user = await self._client.fetch_user(int(recipient_id))
        await user.send(text)

    async def close(self) -> None:
        await self._client.close()
