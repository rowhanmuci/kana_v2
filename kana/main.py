"""入口：接線所有層並啟動 Bot。

  config → Database(migrate) → Repositories → LLMClient → ConversationService → Discord
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .adapters.discord_adapter import build_client
from .config import get_settings
from .domain.conversation import ConversationService
from .infra.embeddings import sqlite_vec_available
from .infra.llm import LLMClient
from .infra.repository import Repositories

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("kana.log", encoding="utf-8")],
)
logger = logging.getLogger("kana.main")


async def _main() -> None:
    settings = get_settings()
    if not settings.discord_bot_token:
        logger.error("DISCORD_BOT_TOKEN 未設定，無法啟動")
        sys.exit(1)

    logger.info("sqlite-vec 檢查（Phase 2 需要）：%s", sqlite_vec_available())

    repos = await Repositories.create(settings.database_path)
    logger.info("資料庫就緒：%s", settings.database_path)

    llm = LLMClient.from_settings(settings)
    conversation = ConversationService(repos, llm)
    client = build_client(conversation)

    logger.info("啟動加奈 v2（chat=%s）", settings.chat_model)
    try:
        await client.start(settings.discord_bot_token)
    finally:
        await client.close()
        await repos.close()


def run() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉")


if __name__ == "__main__":
    run()
