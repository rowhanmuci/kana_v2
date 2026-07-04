"""型別層：每張表一個 Pydantic model。

系統內流動的都是這些型別物件，不再是裸 dict。
DB 邊界（repository）負責 row → model、model → 參數的轉換，
時間欄位一律在這層解析成 aware datetime。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..util import now_utc, parse_iso


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_dt(cls, v, info):
        # 讓任何宣告為 datetime 的欄位都能吃 ISO 字串
        ann = cls.model_fields[info.field_name].annotation
        if ann in (datetime, "datetime") and isinstance(v, str):
            return parse_iso(v)
        return v


class PersonaState(_Base):
    character_id: str = ""
    current_activity: str = "idle"
    current_mood: str = "content"
    energy_level: int = 100
    updated_at: datetime = Field(default_factory=now_utc)


class Relationship(_Base):
    character_id: str = ""
    user_id: str
    display_name: str = ""
    first_met: datetime = Field(default_factory=now_utc)
    last_interaction: datetime = Field(default_factory=now_utc)
    familiarity: int = 0
    affection: int = 0
    relationship_stage: str = "stranger"
    known_facts: list[str] = Field(default_factory=list)
    inside_jokes: list[str] = Field(default_factory=list)
    last_mood_toward: str = "neutral"


class Message(_Base):
    id: int | None = None
    character_id: str = ""
    user_id: str
    role: str
    content: str
    created_at: datetime = Field(default_factory=now_utc)


class EpisodicMemory(_Base):
    id: int | None = None
    character_id: str = ""
    user_id: str | None = None
    kind: str
    content: str
    importance: float = 0.5
    created_at: datetime = Field(default_factory=now_utc)
