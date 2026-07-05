"""非同步 SQLite 封裝。

設計要點（根治舊版的 `database is locked`）：
  - 單一長壽連線：aiosqlite 在自己的背景執行緒裡逐一排隊執行所有操作，
    本身就把同進程內的存取序列化了——這就消除了 lock 競爭。
  - WAL + busy_timeout：對外部讀取者（DB Browser 等）也友善。
  - 寫入鎖：多語句交易（read-modify-write）用 _write_lock 包起來保證原子。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("kana.db")

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# 向量表的 DDL 放這裡而不是 schema.sql：它依賴 sqlite-vec extension，
# extension 載入失敗時要能跳過（記憶檢索退化為 recency+importance，不擋啟動）。
_VEC_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec "
    "USING vec0(embedding float[{dim}] distance_metric=cosine)"
)


class Database:
    def __init__(self, path: str, embedding_dim: int = 1024):
        self._path = path
        self._embedding_dim = embedding_dim
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self.vec_enabled = False

    async def connect(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.commit()
        await self._load_vec()

    async def _load_vec(self) -> None:
        try:
            import sqlite_vec

            await self._conn.enable_load_extension(True)
            await self._conn.load_extension(sqlite_vec.loadable_path())
            await self._conn.enable_load_extension(False)
            self.vec_enabled = True
        except Exception as e:
            logger.warning("sqlite-vec 載入失敗，向量檢索停用：%s", e)
            self.vec_enabled = False

    async def migrate(self) -> None:
        assert self._conn is not None, "connect() 尚未呼叫"
        script = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._write_lock:
            await self._conn.executescript(script)
            if self.vec_enabled:
                await self._conn.execute(_VEC_DDL.format(dim=self._embedding_dim))
            await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── 寫入 ──────────────────────────────────────────────
    async def execute(self, sql: str, params: tuple = ()) -> int:
        """執行一句寫入，回傳 lastrowid。"""
        assert self._conn is not None
        async with self._write_lock:
            cur = await self._conn.execute(sql, params)
            await self._conn.commit()
            return cur.lastrowid

    @property
    def write_lock(self) -> asyncio.Lock:
        """需要把多句寫入綁成一筆交易時，用 `async with db.write_lock:` 包起來。"""
        return self._write_lock

    async def execute_in_tx(self, statements: list[tuple[str, tuple]]) -> None:
        """多句寫入綁成一筆交易。"""
        assert self._conn is not None
        async with self._write_lock:
            for sql, params in statements:
                await self._conn.execute(sql, params)
            await self._conn.commit()

    # ── 讀取 ──────────────────────────────────────────────
    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        assert self._conn is not None
        cur = await self._conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        assert self._conn is not None
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)
