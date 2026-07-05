"""設定層：所有可調參數的單一來源。

從 .env 讀取，型別驗證，提供 call_type → 模型路由。
模型/provider 切換（本地 vs 雲、Qwen vs Gemma）只改這裡，不動 domain 邏輯。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ModelRoute:
    """一個呼叫類型對應的 provider / 模型 / token 上限。"""
    provider: str
    model: str
    max_tokens: int
    temperature: float = 0.8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 角色與通道 ──
    character_id: str = "kana"            # characters/ 下的角色包目錄名
    characters_dir: str = "./characters"
    adapter: str = "discord"              # 對話通道：discord | cli（env: ADAPTER）
    default_provider: str = "ollama"      # LLM provider（route() 讀它，切雲改這裡）

    # ── Discord（adapter=discord 時必填）──
    discord_bot_token: str = ""

    # ── 本地模型 ──
    ollama_host: str = "http://localhost:11434"
    chat_model: str = "qwen3:14b"
    # 背景呼叫（關係抽取等）預設跟 chat 同一顆：12GB VRAM 放不下兩個模型，
    # 分開會導致 Ollama 每次呼叫交換模型（幾秒的載入）。要省算力可設 UTILITY_MODEL=qwen3:8b。
    utility_model: str = "qwen3:14b"
    embedding_model: str = "bge-m3"

    # ── 對話節奏 ──
    # 延遲整體縮放：1.0 = 真實節奏（idle 中位數約 1 分鐘）；測試/調校設 0 立即回。
    pacing_scale: float = 1.0

    # ── 記憶檢索（三項加權，見 domain/memory.py；調味靠實測手感）──
    memory_recall_k: int = 5             # 每次注入幾筆記憶
    memory_candidate_pool: int = 50      # KNN 候選數
    memory_w_relevance: float = 0.55
    memory_w_recency: float = 0.25
    memory_w_importance: float = 0.20
    memory_half_life_days: float = 3.0
    memory_cooldown_hours: float = 6.0   # 剛想起過的事的冷卻
    memory_min_age_minutes: int = 90     # 太新的不撈（還在對話歷史裡）

    # ── 資料庫 ──
    database_path: str = "./data/kana.db"

    # ── 選填憑證 ──
    anthropic_api_key: str = ""
    threads_access_token: str = ""
    threads_user_id: str = ""
    admin_channel_id: int | None = None
    owner_user_id: int | None = None
    youtube_api_key: str = ""

    # ── 時區 ──
    timezone: str = "Asia/Taipei"

    # 預設全部走本地 Ollama。chat 吃人格用 chat_model，背景用 utility_model。
    # 日後要把 chat 切回雲端，只改這個 method（或 DEFAULT_PROVIDER env）即可。
    def route(self, call_type: str) -> ModelRoute:
        provider = self.default_provider
        table: dict[str, ModelRoute] = {
            "chat":       ModelRoute(provider, self.chat_model, 500, 0.85),
            "social":     ModelRoute(provider, self.chat_model, 2000, 0.85),
            "commitment": ModelRoute(provider, self.chat_model, 400, 0.8),
            "memory":     ModelRoute(provider, self.utility_model, 900, 0.4),
            "heartbeat":  ModelRoute(provider, self.utility_model, 200, 0.5),
            "browse":     ModelRoute(provider, self.utility_model, 400, 0.6),
            "proactive":  ModelRoute(provider, self.utility_model, 250, 0.8),
            "diary":      ModelRoute(provider, self.utility_model, 800, 0.8),
        }
        return table.get(call_type, ModelRoute(provider, self.utility_model, 400, 0.7))


@lru_cache
def get_settings() -> Settings:
    return Settings()
