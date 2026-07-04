"""型別化 repository：SQL 全收在這層，對外只回傳 / 接受 model 物件。

Domain 與 Cognitive 層永遠看不到 SQL 或裸 row。
日後若換 DB（Postgres 等），只動這一層。

character_id 在 Repositories.create() 時綁定一次，各 repo 自動注入所有 SQL——
domain 呼叫端不用帶 character_id（單角色運行零負擔），
但 DB 是多角色 ready：要同進程跑第二個角色，開第二個 Repositories 實例即可。
"""

from __future__ import annotations

import json

from .db import Database
from .models import EpisodicMemory, Message, PersonaState, Relationship
from ..util import now_utc, to_iso


class PersonaStateRepo:
    def __init__(self, db: Database, character_id: str):
        self._db = db
        self._char = character_id

    async def get(self) -> PersonaState:
        row = await self._db.fetchone(
            "SELECT * FROM persona_state WHERE character_id = ?", (self._char,)
        )
        if row is None:
            state = PersonaState(character_id=self._char)
            await self._db.execute(
                "INSERT INTO persona_state "
                "(character_id, current_activity, current_mood, energy_level, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._char, state.current_activity, state.current_mood,
                 state.energy_level, to_iso(state.updated_at)),
            )
            return state
        return PersonaState(**dict(row))

    async def update(self, **fields) -> None:
        allowed = {"current_activity", "current_mood", "energy_level"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        await self.get()  # 確保 row 存在
        cols = ", ".join(f"{k} = ?" for k in sets)
        params = tuple(sets.values()) + (to_iso(now_utc()), self._char)
        await self._db.execute(
            f"UPDATE persona_state SET {cols}, updated_at = ? WHERE character_id = ?", params
        )


class RelationshipRepo:
    def __init__(self, db: Database, character_id: str):
        self._db = db
        self._char = character_id

    async def get(self, user_id: str) -> Relationship | None:
        row = await self._db.fetchone(
            "SELECT * FROM relationship WHERE character_id = ? AND user_id = ?",
            (self._char, user_id),
        )
        if row is None:
            return None
        data = dict(row)
        data["known_facts"] = json.loads(data.get("known_facts") or "[]")
        data["inside_jokes"] = json.loads(data.get("inside_jokes") or "[]")
        return Relationship(**data)

    async def ensure(self, user_id: str, display_name: str) -> Relationship:
        existing = await self.get(user_id)
        if existing is not None:
            return existing
        rel = Relationship(character_id=self._char, user_id=user_id, display_name=display_name)
        await self._db.execute(
            "INSERT INTO relationship "
            "(character_id, user_id, display_name, first_met, last_interaction, familiarity, "
            " affection, relationship_stage, known_facts, inside_jokes, last_mood_toward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rel.character_id, rel.user_id, rel.display_name,
                to_iso(rel.first_met), to_iso(rel.last_interaction),
                rel.familiarity, rel.affection, rel.relationship_stage,
                json.dumps(rel.known_facts, ensure_ascii=False),
                json.dumps(rel.inside_jokes, ensure_ascii=False),
                rel.last_mood_toward,
            ),
        )
        return rel

    async def update(self, user_id: str, **fields) -> None:
        allowed = {
            "display_name", "last_interaction", "familiarity", "affection",
            "relationship_stage", "known_facts", "inside_jokes", "last_mood_toward",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols, params = [], []
        for k, v in sets.items():
            cols.append(f"{k} = ?")
            if k in ("known_facts", "inside_jokes"):
                params.append(json.dumps(v, ensure_ascii=False))
            elif k == "last_interaction":
                params.append(to_iso(v) if not isinstance(v, str) else v)
            else:
                params.append(v)
        params += [self._char, user_id]
        await self._db.execute(
            f"UPDATE relationship SET {', '.join(cols)} WHERE character_id = ? AND user_id = ?",
            tuple(params),
        )

    async def touch(self, user_id: str) -> None:
        """更新 last_interaction 為現在。"""
        await self.update(user_id, last_interaction=to_iso(now_utc()))


class MessageRepo:
    def __init__(self, db: Database, character_id: str):
        self._db = db
        self._char = character_id

    async def add(self, user_id: str, role: str, content: str) -> Message:
        msg = Message(character_id=self._char, user_id=user_id, role=role, content=content)
        rowid = await self._db.execute(
            "INSERT INTO message_log (character_id, user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg.character_id, msg.user_id, msg.role, msg.content, to_iso(msg.created_at)),
        )
        msg.id = rowid
        return msg

    async def recent(self, user_id: str, limit: int = 10) -> list[Message]:
        """回傳最近 limit 則，依時間正序（舊→新）。"""
        rows = await self._db.fetchall(
            "SELECT * FROM message_log WHERE character_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (self._char, user_id, limit),
        )
        return [Message(**dict(r)) for r in reversed(rows)]


class EpisodicMemoryRepo:
    def __init__(self, db: Database, character_id: str):
        self._db = db
        self._char = character_id

    async def add(self, kind: str, content: str, *, user_id: str | None = None,
                  importance: float = 0.5) -> EpisodicMemory:
        mem = EpisodicMemory(character_id=self._char, kind=kind, content=content,
                             user_id=user_id, importance=importance)
        rowid = await self._db.execute(
            "INSERT INTO memory_episodic (character_id, user_id, kind, content, importance, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mem.character_id, mem.user_id, mem.kind, mem.content,
             mem.importance, to_iso(mem.created_at)),
        )
        mem.id = rowid
        return mem

    async def recent(self, limit: int = 10, *, kind: str | None = None) -> list[EpisodicMemory]:
        if kind is not None:
            rows = await self._db.fetchall(
                "SELECT * FROM memory_episodic WHERE character_id = ? AND kind = ? "
                "ORDER BY id DESC LIMIT ?",
                (self._char, kind, limit),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM memory_episodic WHERE character_id = ? ORDER BY id DESC LIMIT ?",
                (self._char, limit),
            )
        return [EpisodicMemory(**dict(r)) for r in rows]


class Repositories:
    """所有 repository 的容器，持有 Database 並綁定一個角色。"""

    def __init__(self, db: Database, character_id: str):
        self.db = db
        self.character_id = character_id
        self.persona = PersonaStateRepo(db, character_id)
        self.relationship = RelationshipRepo(db, character_id)
        self.message = MessageRepo(db, character_id)
        self.memory = EpisodicMemoryRepo(db, character_id)

    @classmethod
    async def create(cls, path: str, character_id: str) -> "Repositories":
        db = Database(path)
        await db.connect()
        await db.migrate()
        return cls(db, character_id)

    async def close(self) -> None:
        await self.db.close()
