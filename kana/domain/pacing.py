"""對話節奏：延遲、拆條、緩衝窗口——全部是純函式決策，不做 I/O。

分層原則：domain 負責「等多久、拆幾條、間隔多少」的決策，
adapter 負責實際的 sleep / typing / send（CLI 直接忽略延遲）。
延遲用 log-normal 分布模擬人類回訊的長尾：多數落在中位數附近、偶爾拖很久。
參數表沿用 v1 實測值（v1 delay.py），但改成無狀態純函式，可單元測試。

角色無關的行為參數放這裡當常數；會想在部署間調的（整體縮放）走 config 的 PACING_SCALE。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..infra.models import PersonaState, Relationship

# ── 各活動的基礎延遲（秒）與離散度 ──
_ACTIVITY_PARAMS: dict[str, tuple[float, float]] = {
    "commuting":      (1800, 0.9),
    "lab":            (480, 0.8),
    "writing_thesis": (240, 1.1),   # 逃避論文時反而容易秒回
    "watching_anime": (200, 0.7),
    "reading":        (300, 0.8),
    "listening_music": (150, 0.8),
    "idle":           (75, 0.9),
}
_DEFAULT_PARAMS = (120, 0.8)

# ── 心情對離散度的影響 ──
_MOOD_SIGMA: dict[str, float] = {
    "focused": -0.15, "content": -0.10, "lazy": 0.20,
    "anxious": 0.15, "distracted": 0.30, "irritated": 0.25,
}

_DELAY_MIN, _DELAY_MAX = 3.0, 7200.0
_MAX_PARTS = 3          # 一次回覆最多拆幾條
_TYPING_CPS = 6.0       # 模擬打字速度（字/秒），決定 part 間隔
_GAP_MIN, _GAP_MAX = 1.5, 12.0
_BUFFER_MIN, _BUFFER_MAX = 4.0, 9.0


@dataclass(frozen=True)
class ReplyPlan:
    """adapter 據此執行回覆：先等 initial_delay，再依 gaps 間隔送出各 part。

    parts 為空代表這次不回（睡著、體力耗盡、或 LLM 空回覆）。
    gaps 長度 = len(parts) - 1（第一條在 initial_delay 後立即送出）。
    """

    parts: list[str] = field(default_factory=list)
    initial_delay: float = 0.0
    gaps: list[float] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.parts


def delay_params(
    state: PersonaState,
    rel: Relationship | None,
    incoming_text: str,
) -> tuple[float, float] | None:
    """回傳 log-normal 的 (mu, sigma)；None 代表這次不回。純函式、確定性，可直接測。"""
    if state.current_activity == "sleeping":
        return None
    if state.energy_level < 20:
        return None
    familiarity = rel.familiarity if rel else 0
    if state.current_mood == "irritated" and familiarity < 50:
        return None

    base, sigma = _ACTIVITY_PARAMS.get(state.current_activity, _DEFAULT_PARAMS)

    # 好感度越高回得越快，中位數最多縮短 55%
    affection = rel.affection if rel else 0
    mu = math.log(base * (1.0 - (max(0, affection) / 1000) * 0.55))

    sigma += _MOOD_SIGMA.get(state.current_mood, 0.0)

    # 提到她記得的事（known_facts）→ 回得更快：在意對方記不記得她說過的話
    if rel and any(f[:10] in incoming_text for f in rel.known_facts if len(f) > 3):
        mu -= 0.5
        sigma -= 0.1

    return mu, max(0.3, sigma)


def split_reply(text: str, max_parts: int = _MAX_PARTS) -> list[str]:
    """把回覆按空行拆成多條短訊（像真人連發），超過上限的尾段合併。"""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) > max_parts:
        parts = parts[: max_parts - 1] + ["\n\n".join(parts[max_parts - 1:])]
    return parts


def plan_reply(
    reply_text: str,
    state: PersonaState,
    rel: Relationship | None,
    incoming_text: str,
    *,
    scale: float = 1.0,
    rng: random.Random | None = None,
) -> ReplyPlan:
    """把 LLM 回覆包成帶節奏的 ReplyPlan。scale 是整體縮放（config PACING_SCALE，測試設 0）。"""
    rng = rng or random
    parts = split_reply(reply_text)
    if not parts:
        return ReplyPlan()

    params = delay_params(state, rel, incoming_text)
    if params is None:
        return ReplyPlan()

    mu, sigma = params
    delay = min(max(rng.lognormvariate(mu, sigma), _DELAY_MIN), _DELAY_MAX)

    # part 間隔 ≈ 打下一條的時間，帶一點隨機
    gaps = [
        min(max(len(p) / _TYPING_CPS * rng.uniform(0.7, 1.3), _GAP_MIN), _GAP_MAX)
        for p in parts[1:]
    ]
    return ReplyPlan(
        parts=parts,
        initial_delay=delay * scale,
        gaps=[g * scale for g in gaps],
    )


def buffer_window(rng: random.Random | None = None) -> float:
    """使用者連發訊息的合併等待窗口（秒）：最後一則之後靜默這麼久才開始處理。"""
    rng = rng or random
    return rng.uniform(_BUFFER_MIN, _BUFFER_MAX)
