-- 加奈 v2 資料庫 schema
-- 規則：所有 timestamp 一律 TEXT，存 ISO-8601 UTC 字串（見 kana/util.py）。
-- 全部 IF NOT EXISTS，可重複套用。

-- 加奈當前狀態（單筆，id=1）
CREATE TABLE IF NOT EXISTS persona_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    current_activity TEXT    NOT NULL DEFAULT 'idle',
    current_mood     TEXT    NOT NULL DEFAULT 'content',
    energy_level     INTEGER NOT NULL DEFAULT 100,
    updated_at       TEXT    NOT NULL
);

-- 與每位使用者的關係
CREATE TABLE IF NOT EXISTS relationship (
    user_id            TEXT    PRIMARY KEY,
    display_name       TEXT    NOT NULL DEFAULT '',
    first_met          TEXT    NOT NULL,
    last_interaction   TEXT    NOT NULL,
    familiarity        INTEGER NOT NULL DEFAULT 0,
    affection          INTEGER NOT NULL DEFAULT 0,
    relationship_stage TEXT    NOT NULL DEFAULT 'stranger',
    known_facts        TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    inside_jokes       TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    last_mood_toward   TEXT    NOT NULL DEFAULT 'neutral'
);

-- 原始對話紀錄
CREATE TABLE IF NOT EXISTS message_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT    NOT NULL,
    role       TEXT    NOT NULL,   -- 'user' | 'assistant'
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_user ON message_log (user_id, id);

-- 情節記憶（Phase 2 接向量檢索；Phase 0 先建表）
CREATE TABLE IF NOT EXISTS memory_episodic (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT,                          -- 可為 NULL（關於她自己的記憶）
    kind       TEXT    NOT NULL,              -- conversation | self | world | reflection | event
    content    TEXT    NOT NULL,
    importance REAL    NOT NULL DEFAULT 0.5,  -- 0..1，檢索加權用
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_episodic (created_at);
