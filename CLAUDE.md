# CLAUDE.md

加奈 v2 — 本地模型驅動的 AI 人格引擎（角色資料化，Discord 只是其中一個通道）。完整設計地圖見 [REBUILD_PLAN.md](REBUILD_PLAN.md)，這裡只記日常開發需要的脈絡。

## 現況

**Phase 2（檢索式記憶）完成。** `domain/memory.py` 三項加權召回（relevance/recency/importance＋冷卻懲罰，權重在 config）、sqlite-vec + bge-m3 向量化、跨 session 召回已實測（清史後仍想起「麻糬」）。Phase 1 的對話節奏（`pacing.py`、`InboundMessage → ReplyPlan` 契約）與關係演化（`relationship.py`，淨化層防 v1 髒資料死因）都在跑，55 個自動化測試綠燈。v1 的承諾抽取確定不做（實測效果不好）。
語氣迭代靠 `python -m kana cli` 持續（已修：假承諾句式、編造歌名；括號舞台指示偶發，繼續壓）。下一步是 Phase 3（生活：每日事件生成器、affect、life-plan）。各 phase 的範圍與完成標準見 REBUILD_PLAN.md 第 6 節。

## 架構分層（依賴方向由上往下，下層不認識上層）

```
characters/<id>/  角色包·純資料（core/speech/never/backstory/tastes/notes），被 domain 載入
adapters/   純 I/O，實作 Protocol，config 驅動選擇
            對話型 ChatAdapter：discord_adapter · cli_adapter
            發文型 PostingAdapter：threads（遠期，介面已定義於 base.py）
  ↓
domain/     流程編排，無 I/O 細節（character、persona、conversation）
  ↓
infra/      被共用的基礎設施（db、models、repository、llm、embeddings、config）
```

- [kana/config.py](kana/config.py) — 設定單一來源。`Settings.route(call_type)` 把每種呼叫（chat/social/memory/heartbeat…）對應到 provider/model/token。**切換本地↔雲（`DEFAULT_PROVIDER`）、換模型、換通道（`ADAPTER`）、換角色（`CHARACTER_ID`）都只改這裡**，不動 domain。
- [kana/domain/character.py](kana/domain/character.py) — 角色包載入。固定檔名約定：core/speech/never 必要、backstory/tastes 選配、notes/ 是機器可改寫區（Phase 4 知識種子）。
- [kana/domain/persona.py](kana/domain/persona.py) — `PersonaPromptBuilder`：靜態前綴（core+speech+背景+品味）快取、動態段（狀態/關係/`extra_sections`）、never 壓陣。Phase 2+ 的記憶/事件/筆記都從 `extra_sections` 注入，不改簽名。
- [kana/adapters/base.py](kana/adapters/base.py) — adapter 介面。adapter 只認識 `InboundMessage` 與 `ReplyPlan`，handler 由 main 注入，不認識 domain service。節奏分工：domain 決策（[pacing.py](kana/domain/pacing.py)），adapter 執行（sleep/typing/send）。
- [kana/util.py](kana/util.py) — 時間規則的單一來源（aware UTC ↔ ISO-8601）+ `user_key()`（user_id 命名空間的單一來源）+ `humanize_age()`（prompt 用相對時間）。
- [kana/infra/db.py](kana/infra/db.py) — aiosqlite 單長壽連線 + `_write_lock` 序列化寫入。多句原子交易用 `execute_in_tx`。
- [kana/infra/models.py](kana/infra/models.py) — 每張表一個 Pydantic model，系統內流動的是型別物件不是裸 dict。
- [kana/infra/repository.py](kana/infra/repository.py) — SQL 全收在這層；JSON 欄位在邊界序列化。`Repositories.create(path, character_id)` 建構時綁定角色，domain 呼叫端不帶 character_id。
- [kana/infra/llm.py](kana/infra/llm.py) — `LLMProvider` 抽象 + `OllamaProvider` + `FakeProvider`（測試用）。`chat_json` 走結構化輸出。
- [kana/main.py](kana/main.py) — 接線入口：config → 角色包 → DB(綁角色) → LLM → builder → conversation → adapter（factory 選擇）。

## 不可動搖的設計約束（違反就回到舊版的 bug）

1. **時間一律 UTC ISO-8601 字串進出 DB**，只用 [util.py](kana/util.py) 的 `now_utc`/`to_iso`/`parse_iso`。別在別處 `datetime.fromisoformat`。
2. **SQL 只准出現在 [repository.py](kana/infra/repository.py)。** domain / adapter 永遠拿 model 物件，看不到 row 或 SQL。換 DB 只動 repository。
3. **所有寫入走 `Database` 的 `execute`/`execute_in_tx`**（已被 `_write_lock` 序列化）。不要自己開連線繞過它——`database locked` 就是這樣回來的。
4. **模型/provider 路由集中在 `Settings.route()`。** 不要在 domain 裡寫死模型名或 token 上限。
5. **新表 → 同步加 schema.sql、Pydantic model、repository CRUD 三者**，邊界解析一次；新表一律帶 `character_id`。
6. **人格內容只准在 `characters/`，不准進 .py。** 引擎程式碼 grep 不到任何角色設定文字（v1 的 PERSONA_BASE 硬編碼且與 persona.md 不同步，就是反例）。換角色 = 換目錄 + `CHARACTER_ID`。
7. **user_id 一律 `channel:sender_id` 格式**，組合點只在 domain（`conversation.handle` 用 `util.user_key`）。adapter 只碰平台原生 id。
8. **平台 I/O 只准實作 [adapters/base.py](kana/adapters/base.py) 的 Protocol。** adapter 不 import domain service，handler 由 main 注入。

## 開發指令

環境是 miniconda 的 `ml` env（Python 3.10.18）。

```bash
pytest -q                    # 自動化測試（用 FakeProvider，不需 Ollama / 不需網路）
python -m kana cli           # 終端機直接和角色對話（需 Ollama，不需 Discord token）——調語氣的最短迴路
                             # 位置參數選通道，免設 env（PowerShell/cmd 通用）；CLI 模式 log 只寫 kana.log
python -m kana               # Discord bot（需 .env 的 DISCORD_BOT_TOKEN + Ollama 已 pull 模型）
pip install -e ".[dev]"      # 安裝依賴
```

## 測試策略

- **自動化測試不碰 LLM**：用 [FakeProvider](kana/infra/llm.py) 注入假回覆，所以 `pytest` 不需要 pull 任何模型、不需網路。涵蓋型別層、寫入序列化（含並發無 lock）、模型路由、JSON 解析、角色包載入與 prompt 組裝、角色資料隔離、user_id 命名空間、對話 round-trip。
- **真實端到端要 Ollama**：語氣調校先用 `python -m kana cli` 跑本地 Qwen（`ollama pull qwen3:14b`，退路 qwen3:8b）；Discord 行為才需要 token。embedding 的 bge-m3 到 Phase 2 才需要。
- 新功能優先寫成可用 FakeProvider 測的單元，把「要真模型才驗得到」的部分壓到最小。

## 慣例

- 全繁體中文註解與 log。
- 每個檔案開頭有 docstring 說明該模組的職責與設計理由，沿用這個風格。
- `call_type` 是路由的 key，新增背景行為時先在 `route()` 註冊對應的 token/temperature。
- 角色包的 `never.md` 是調校精華（反 AI 腔清單），實測發現新的 AI 腔就往裡加，不要加進程式。
