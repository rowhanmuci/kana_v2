"""入口：接線所有層並啟動。

  config → 角色包 → Database(migrate, 綁 character_id) → LLMClient
        → PersonaPromptBuilder → ConversationService → adapter（config 驅動選擇）

換通道：ADAPTER=cli（不需 Discord token，終端機直接對話）。
換角色：CHARACTER_ID=<characters/ 下的目錄名>。
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .adapters.base import ChatAdapter
from .adapters.cli_adapter import CliAdapter
from .adapters.discord_adapter import DiscordAdapter
from .config import Settings, get_settings
from .domain.character import load_character
from .domain.conversation import ConversationService
from .domain.persona import PersonaPromptBuilder
from .infra.embeddings import sqlite_vec_available
from .infra.llm import LLMClient
from .infra.repository import Repositories

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("kana.log", encoding="utf-8")],
)
logger = logging.getLogger("kana.main")


def _build_adapter(settings: Settings) -> ChatAdapter:
    """config 驅動的通道選擇。加新通道：實作 ChatAdapter 後在這裡註冊一行。"""
    if settings.adapter == "discord":
        if not settings.discord_bot_token:
            logger.error("adapter=discord 但 DISCORD_BOT_TOKEN 未設定，無法啟動")
            sys.exit(1)
        return DiscordAdapter(settings.discord_bot_token)
    if settings.adapter == "cli":
        return CliAdapter()
    logger.error("未知的 adapter：%s（支援 discord | cli）", settings.adapter)
    sys.exit(1)


async def _main() -> None:
    settings = get_settings()

    character = load_character(settings.characters_dir, settings.character_id)
    logger.info("角色載入：%s（id=%s）", character.name, character.id)

    adapter = _build_adapter(settings)
    logger.info("sqlite-vec 檢查（Phase 2 需要）：%s", sqlite_vec_available())

    repos = await Repositories.create(settings.database_path, character.id)
    logger.info("資料庫就緒：%s", settings.database_path)

    llm = LLMClient.from_settings(settings)
    builder = PersonaPromptBuilder(character)
    conversation = ConversationService(repos, llm, builder)

    logger.info("啟動 %s v2（adapter=%s, chat=%s）", character.name, adapter.name, settings.chat_model)
    try:
        await adapter.run(conversation.handle)
    finally:
        await adapter.close()
        await repos.close()


def run() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉")


if __name__ == "__main__":
    run()
