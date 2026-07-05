"""Adapter 介面：任何平台 I/O 都實作這裡的 Protocol 之一。

兩類通道：
  - ChatAdapter：對話型（Discord、CLI、未來 Telegram）——收訊息、回覆、主動送出
  - PostingAdapter：主動發文型（Threads，遠期掛回）——先定義介面，不實作

adapter 只認識 InboundMessage 與 ReplyPlan，不認識 domain service：
handler 由 main 接線時注入，依賴方向維持 adapters → domain 單向。
節奏分工：domain 決策（等多久、拆幾條），adapter 執行（sleep/typing/send）；
CLI 這種即時通道可以忽略延遲，只送 parts。
用 Protocol 而非 ABC：adapter 之間沒有共享實作，只需要結構相容。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from ..domain.conversation import InboundMessage
from ..domain.pacing import ReplyPlan

# 收到一則入站訊息 → 帶節奏的回覆計畫（parts 為空代表不回）
MessageHandler = Callable[[InboundMessage], Awaitable[ReplyPlan]]


@runtime_checkable
class ChatAdapter(Protocol):
    """對話型通道。"""

    name: str

    async def run(self, on_message: MessageHandler) -> None:
        """啟動事件迴圈，把每則入站訊息交給 on_message，直到通道關閉。"""
        ...

    async def send(self, recipient_id: str, text: str) -> None:
        """主動送訊息給某人（Phase 3 proactive 用）。recipient_id 是平台原生 id。"""
        ...

    async def close(self) -> None:
        ...


@runtime_checkable
class PostingAdapter(Protocol):
    """主動發文型通道（Threads 遠期）。"""

    name: str

    async def publish(self, text: str) -> str:
        """發一篇公開貼文，回傳貼文 id。"""
        ...

    async def fetch_replies(self, post_id: str) -> list[InboundMessage]:
        """抓某篇貼文的新留言。"""
        ...
