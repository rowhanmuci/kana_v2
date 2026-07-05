"""CLI adapter：在終端機和角色對話，不需要 Discord token。

實作 ChatAdapter。用途是人格語氣調校的最短迴路：
  ADAPTER=cli python -m kana
輸入 /exit（或 Ctrl-C / EOF）結束。
"""

from __future__ import annotations

import asyncio
import logging

from .base import MessageHandler
from ..domain.conversation import InboundMessage

logger = logging.getLogger("kana.cli")


class CliAdapter:
    name = "cli"

    def __init__(self, sender_id: str = "local", display_name: str = "Console"):
        self._sender_id = sender_id
        self._display_name = display_name
        self._closed = False

    async def run(self, on_message: MessageHandler) -> None:
        print("（CLI 模式：直接輸入訊息，/exit 結束）")
        while not self._closed:
            try:
                text = await asyncio.to_thread(input, "你> ")
            except (EOFError, KeyboardInterrupt):
                break
            text = text.strip()
            if not text:
                continue
            if text == "/exit":
                break

            msg = InboundMessage(
                channel=self.name,
                sender_id=self._sender_id,
                display_name=self._display_name,
                text=text,
            )
            plan = await on_message(msg)
            if plan.is_empty:
                print("（沒有回覆）")
                continue
            # CLI 是調語氣的迴路，不模擬延遲；只在多條時提示原本的節奏
            if plan.initial_delay > 1:
                print(f"（{plan.initial_delay:.0f} 秒後…）")
            for part in plan.parts:
                print(part)

    async def send(self, recipient_id: str, text: str) -> None:
        print(f"（主動訊息 → {recipient_id}）{text}")

    async def close(self) -> None:
        self._closed = True
