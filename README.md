# 加奈 v2

本地模型驅動的 Discord AI 人格 bot。重塑藍圖見 [`REBUILD_PLAN.md`](./REBUILD_PLAN.md)。

> 目前進度：**Phase 0（骨架地基）完成**。可用本地 Qwen 回 DM、DB 全走型別層、無 database locked。

## 架構

```
kana/
├── config.py            設定單一來源（call_type → 模型路由）
├── infra/               基礎設施
│   ├── db.py            aiosqlite 單連線 + WAL + 寫入序列化
│   ├── models.py        Pydantic 型別層（每張表一個 model）
│   ├── repository.py    型別化 CRUD（SQL 只在這層）
│   ├── llm.py           provider 抽象 + 結構化輸出（Ollama）
│   ├── embeddings.py    本地 embedding + sqlite-vec（Phase 2 接檢索）
│   └── schema.sql       v2 schema（timestamp 一律 ISO-8601 UTC）
├── domain/              流程編排（無 I/O 細節）
│   ├── persona.py       人格組裝
│   └── conversation.py  DM round-trip
├── adapters/
│   └── discord_adapter.py  薄 I/O，只處理 DM
└── main.py              接線入口
```

## 環境需求

- Python 3.10+
- [Ollama](https://ollama.com)（本地模型 runtime）
- Discord Bot Token（開啟 Message Content Intent）

## 安裝

```bash
pip install -e ".[dev]"

# 拉模型（12GB 顯存）
ollama pull qwen3:14b     # 對話；退路 qwen3:8b
ollama pull qwen3:8b      # 背景呼叫
ollama pull bge-m3        # embedding（Phase 2 用）
```

複製 `.env.example` 為 `.env`，至少填 `DISCORD_BOT_TOKEN`。

## 啟動

```bash
python -m kana
```

## 測試

```bash
pytest -q
```

Phase 0 涵蓋型別層、寫入序列化（含並發無 lock 驗證）、模型路由、結構化 JSON 解析、對話 round-trip。Discord / Ollama 的整合需在本機跑。
