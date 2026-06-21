"""LLM 客戶端：provider 抽象 + 結構化輸出。

- provider 可替換（本地 Ollama / 日後雲端），由 config.route() 決定每個 call_type 走哪個。
- 結構化輸出走 JSON schema（Ollama format 參數），取代舊版的 regex 清 markdown。
- chat 模型預設關閉 Qwen3 的 thinking，並防禦性剝掉 <think>...</think>。
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from ..config import Settings

logger = logging.getLogger("kana.llm")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, *, model: str, messages: list[dict], system: str | None,
                   max_tokens: int, temperature: float, fmt: dict | str | None = None) -> str:
        ...


class OllamaProvider(LLMProvider):
    def __init__(self, host: str, timeout: float = 120.0):
        self._host = host.rstrip("/")
        self._timeout = timeout

    async def chat(self, *, model: str, messages: list[dict], system: str | None,
                   max_tokens: int, temperature: float, fmt: dict | str | None = None) -> str:
        payload: dict = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": False,
            "think": False,  # 關閉 Qwen3 thinking，要保留時改 True
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if fmt is not None:
            payload["format"] = fmt

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = (data.get("message") or {}).get("content", "") or ""
        return _THINK_RE.sub("", content).strip()


class FakeProvider(LLMProvider):
    """測試用：回傳固定字串或自訂 handler。"""

    def __init__(self, handler=None):
        self._handler = handler or (lambda **kw: "（假回覆）")

    async def chat(self, **kwargs) -> str:
        result = self._handler(**kwargs)
        return result


class LLMClient:
    def __init__(self, settings: Settings, providers: dict[str, LLMProvider]):
        self._settings = settings
        self._providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient":
        return cls(settings, {"ollama": OllamaProvider(settings.ollama_host)})

    async def chat(self, call_type: str, messages: list[dict],
                   system: str | None = None, fmt: dict | str | None = None) -> str:
        route = self._settings.route(call_type)
        provider = self._providers[route.provider]
        return await provider.chat(
            model=route.model, messages=messages, system=system,
            max_tokens=route.max_tokens, temperature=route.temperature, fmt=fmt,
        )

    async def chat_json(self, call_type: str, messages: list[dict],
                        system: str | None = None, schema: dict | None = None) -> dict:
        """要求結構化 JSON 輸出並解析。schema 為 JSON schema（Ollama format）。"""
        raw = await self.chat(call_type, messages, system=system, fmt=schema or "json")
        return _parse_json(raw)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    raw = re.sub(r",\s*([}\]])", r"\1", raw)  # 移除 trailing comma
    return json.loads(raw)
