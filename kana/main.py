"""入口：接線所有層並啟動。

  config → 角色包 → Database(migrate, 綁 character_id) → LLMClient
        → PersonaPromptBuilder → ConversationService → adapter（config 驅動選擇）

換通道：`python -m kana cli`（或 env ADAPTER=cli）——不需 Discord token，終端機直接對話。
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

logger = logging.getLogger("kana.main")


def _setup_logging(console: bool) -> None:
    """CLI 模式 log 只寫檔，畫面留給對話；其他模式照舊雙輸出。"""
    handlers: list[logging.Handler] = [logging.FileHandler("kana.log", encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


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


async def _main(adapter_override: str | None = None) -> None:
    settings = get_settings()
    if adapter_override:
        settings.adapter = adapter_override
    _setup_logging(console=settings.adapter != "cli")

    character = load_character(settings.characters_dir, settings.character_id)
    logger.info("角色載入：%s（id=%s）", character.name, character.id)

    adapter = _build_adapter(settings)
    logger.info("sqlite-vec 檢查（Phase 2 需要）：%s", sqlite_vec_available())

    repos = await Repositories.create(settings.database_path, character.id)
    logger.info("資料庫就緒：%s", settings.database_path)

    llm = LLMClient.from_settings(settings)
    builder = PersonaPromptBuilder(character)
    # CLI 是調語氣的迴路，不模擬延遲
    scale = 0.0 if settings.adapter == "cli" else settings.pacing_scale
    conversation = ConversationService(repos, llm, builder, pacing_scale=scale)

    logger.info("啟動 %s v2（adapter=%s, chat=%s）", character.name, adapter.name, settings.chat_model)
    try:
        await adapter.run(conversation.handle)
    finally:
        await adapter.close()
        await conversation.drain()  # 等背景的關係演化跑完再關 DB
        await repos.close()


def run() -> None:
    # `python -m kana cli` 直接指定通道，免設環境變數（PowerShell/cmd 語法不同易踩雷）
    adapter_override = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(_main(adapter_override))
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉")


if __name__ == "__main__":
    run()
