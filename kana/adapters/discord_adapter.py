"""Discord adapter（薄 I/O）：只負責收發，不含任何 domain 邏輯。

Phase 0 只處理 DM round-trip。延遲、緩衝合併、管理員頻道留給 Phase 1+。
"""

from __future__ import annotations

import logging

import discord

from ..domain.conversation import ConversationService

logger = logging.getLogger("kana.discord")


def build_client(conversation: ConversationService) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info("加奈上線：%s (ID: %s)", client.user, client.user.id)

    @client.event
    async def on_message(message: discord.Message):
        if message.author == client.user:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return  # Phase 0 只回 DM

        user_id = str(message.author.id)
        display_name = message.author.display_name or message.author.name
        logger.info("收到 DM：user=%s content=%s", user_id, message.content[:50])

        try:
            async with message.channel.typing():
                reply = await conversation.handle(user_id, display_name, message.content)
        except discord.HTTPException:
            reply = await conversation.handle(user_id, display_name, message.content)

        if reply:
            await message.channel.send(reply)

    return client
