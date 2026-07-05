"""共用工具：時間一律 UTC、ISO-8601 字串作為 DB 邊界格式。

整個系統的時間表示只有兩種狀態：
  - 程式內：aware datetime（UTC）
  - DB 內：ISO-8601 字串（UTC，秒精度）
進出 DB 各解析一次，杜絕 datetime/str 混用造成的型別錯誤。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))


def now_utc() -> datetime:
    """當前時間，aware UTC。"""
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """aware datetime → ISO-8601 UTC 字串（秒精度）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | datetime | None) -> datetime | None:
    """ISO 字串 / datetime → aware UTC datetime。容錯：None → None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_taipei() -> datetime:
    """當前台北時間（給 prompt 顯示用）。"""
    return datetime.now(TAIPEI_TZ)


def user_key(channel: str, sender_id: str) -> str:
    """全系統 user_id 的單一格式：'{channel}:{sender_id}'。

    多通道時避免不同平台的原生 id 撞號；組合點只在 domain（conversation.handle）。
    """
    return f"{channel}:{sender_id}"


def humanize_age(dt: datetime, now: datetime | None = None) -> str:
    """給 prompt 用的相對時間：「剛剛 / N 小時前 / 昨天 / N 天前」。"""
    now = now or now_utc()
    delta = now - dt
    if delta < timedelta(hours=1):
        return "剛剛"
    if delta < timedelta(hours=24):
        return f"{int(delta.total_seconds() // 3600)} 小時前"
    days = int(delta.total_seconds() // 86400)
    if days == 1:
        return "昨天"
    if days < 30:
        return f"{days} 天前"
    return f"{days // 30} 個月前"
