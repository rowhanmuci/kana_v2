"""本地 embedding + sqlite-vec 接線。

Phase 0 只建立介面與本地 provider，並提供 sqlite-vec 可用性檢查。
實際的向量檢索在 Phase 2 接進 memory 模組。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger("kana.embeddings")


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, host: str, model: str, timeout: float = 60.0):
        self._host = host.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._host}/api/embed",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("embeddings", [])


def sqlite_vec_available() -> bool:
    """檢查 sqlite-vec 是否可載入（Phase 2 需要）。"""
    try:
        import sqlite3
        import sqlite_vec  # noqa: F401

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        version = conn.execute("SELECT vec_version()").fetchone()[0]
        conn.close()
        logger.info("sqlite-vec 可用，版本 %s", version)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("sqlite-vec 不可用：%s", e)
        return False
