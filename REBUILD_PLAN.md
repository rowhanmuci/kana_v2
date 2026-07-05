# 加奈 v2 — 重塑藍圖

> 本文件是整個重塑的設計地圖。先讀「核心原則」與「新架構」理解大方向，再照「分階段路線圖」一步步走。
> 舊 code 與舊 DB 全部捨棄，只保留 `.env` 裡的 Discord / Threads 憑證。

---

## 0. 為什麼重塑

三個目標，順位如下：

1. **角色更真實** — 讓加奈像個有生活、會累積、有個性的人，而不是貼著狀態標籤上網的機器。
2. **穩定性** — 根治舊版反覆出現的型別錯誤、`database locked`、JSON 解析失敗、以及因 API 餘額/限流導致的停擺。
3. **可擴展性** — 角色是資料、通道是插件。引擎與「加奈」解耦：未來可承載不同角色（換 `characters/` 目錄即可）、不同平台（Discord 不是必要手段）。

舊版停擺已三週，DB 內含大量型別 bug 殘留資料，無遷移價值；舊 code 問題是結構性的。因此**全部砍掉重來**。

---

## 1. 核心設計原則

**原則一：「在 context 裡」≠「模型真的變了」。**
一個 agent 真正會「變」只有兩條路：
- (a) 累積**結構化、會複利的外部記憶/知識** → 架構問題，不用訓練。
- (b) 改**權重** → 訓練問題（LoRA / DPO）。

舊版只做了最弱的版本（扁平、append-only、靠 recency 撈最近 5 筆），完全沒有複利機制——這是「研究一個領域卻失敗」「她沒有生活」的共同根因。

**原則二：先做架構能解的，訓練留到最後。**
語氣先用「選對底模型 + prompt + 微調前的資料累積」處理；LoRA/DPO 等到 bot 跑起來、產生了對話資料才做。

**原則三：一步一步，每個 phase 都要能單獨跑起來並驗收。**
不追求一次做完所有有機行為。每階段有明確的「完成標準」。

**原則四：模型與儲存都抽象成可替換層。**
本地 vs 雲、Qwen vs Gemma、SQLite vs 未來的 Postgres——都應該是改 config 的事，不是改 domain 邏輯。

**原則五：角色是資料，引擎是程式；通道是插件。**
人格內容永遠不出現在 .py 裡（v1 的 PERSONA_BASE 硬編碼在 client、與 persona.md 不同步，就是反例）。角色住在 `characters/<id>/` 資料目錄，schema 全表帶 `character_id`；任何平台 I/O 都實作 `ChatAdapter`（對話型）或 `PostingAdapter`（發文型），由 config 選擇。換角色、換平台都不改引擎。

---

## 2. 新架構骨架

依賴方向由上往下，下層不認識上層。角色包是純資料，被 domain 載入。

```
characters/<id>/（角色包·純資料，不是程式）
  character.yaml · core.md · speech.md · never.md
  · backstory.md · tastes.md · notes/（機器可改寫區）
       ↘
① Adapters（純 I/O，實作 Protocol，config 驅動選擇）
   對話型 ChatAdapter：discord · cli（人格調校用，零憑證）
   發文型 PostingAdapter：threads（遠期掛回，介面已定義）
        ↓
② Domain Services（流程編排，無 I/O 細節）
   character loader · PersonaPromptBuilder · conversation · proactive · life · social
        ↓
③ Cognitive Core（角色的「腦」——真實感的關鍵，不依賴任何平台，可單獨測試）
   memory（episodic + 檢索） · affect（連續情緒/體力）
   · life-plan（每日行程/事件，心跳推進） · knowledge（會演進的主題理解）
        ↓
④ Infra（被所有層共用）
   llm_client（local/cloud 可換 provider + 結構化輸出）
   · repository（aiosqlite + Pydantic 型別層，綁 character_id）
   · embeddings（本地） · config · scheduler
```

與舊版最大差異有二：(1) 把糾纏在 `bot.py` / `memory.py` 的邏輯抽出成獨立的 **Cognitive Core**，四個真實感槓桿全落在這層、彼此解耦、可單元測試；(2) **角色與通道都外部化**——引擎 grep 不到任何人設文字，user_id 一律 `channel:id` 命名空間，多平台不撞號。

---

## 3. 技術選型（已定案）

| 項目 | 決定 | 理由 |
|------|------|------|
| 資料庫 | **SQLite + `sqlite-vec`**，用 `aiosqlite` 非同步化 | 單機單進程最輕最穩；向量在同一檔案同進程做，零新增服務；解 `database locked` 靠 repo 層寫入序列化，不靠換 DB |
| 型別層 | **Pydantic / dataclass model**，每張表一個 model | DB 邊界解析驗證一次，系統內流動型別物件，根治型別 bug |
| 時間 | 全系統 **UTC ISO-8601 字串**，進出各解析一次 | 根治 `fromisoformat` 那類錯誤 |
| 對話模型 | **本地 Qwen3-14B（Q4，~9GB）** 為主；退路 Qwen3-8B | 12GB 內繁中角色扮演最佳；audio 拿掉後整張卡可專心服務它 |
| embedding | **本地 bge-m3 / multilingual-e5** | 多語、快、好，去掉雲依賴 |
| LLM 抽象 | `llm_client` 把 provider 抽象化，支援 A/B 並排比模型 | 本地/雲、Qwen/Gemma 改 config 即可切換、比較 |
| LLM 結構化輸出 | tool-use / 強制 JSON schema | 根治 `Extra data` / `Unterminated string` |
| 設定 | model 名、排程、門檻、magic number 全收進 `config` | 可調、可測、可切換 |
| runtime | Ollama（或 llama.cpp） | 本地起手最省事，可按需載入/卸載 |
| 角色包格式 | **YAML manifest + Markdown 內容**（`characters/<id>/`） | manifest 要結構化欄位用 YAML；人設是散文、人手編輯用 md（v1 已證明順手）；每檔對應一個 prompt 段、各有不同變動頻率 |
| 通道選擇 | **config 驅動**（`ADAPTER` env：discord / cli） | 加通道＝實作 ChatAdapter + main 註冊一行；CLI 是人格調校的最短迴路 |

> 混合方案保留為選項：若實測 Qwen3-14B 的人格細膩度不夠，可只把 `chat` 切回強模型（API），背景呼叫仍全本地。因 provider 已抽象，這只是 config 一行。

**audio.py 暫不做**：先以對話為主，驗證本地模型撐不撐得住人格。日後要加，是獨立模組掛回去；屆時需處理 Whisper/Demucs 與對話模型的 VRAM 錯開（按需載入或改用較小 Whisper）。

**未來才考慮 Postgres**：只有走向多角色大規模、多進程併發寫、或上雲時才值得。因 repository 把 SQL 收在一層，屆時只動那層。

---

## 4. 記憶系統設計（檢索式 episodic memory）

你的場景是 **agent 記憶檢索**，不是文件 QA RAG，所以跳過 chunking / 複雜 re-rank / query 改寫那些深水區。每筆記憶本來就是短、自包含的一個單位。

**核心：撈什麼不能只看語意相似度。** 採 Generative Agents 的三項加權分數：

```
score = w_rel · relevance(cosine)
      + w_rec · recency(指數衰減)
      + w_imp · importance(情感/重要性 0–1)
```

- `relevance`：當前訊息/話題的向量相似度。
- `recency`：越近越容易被想起；接你本來就有的熟悉度衰減概念。
- `importance`：寫入記憶時由 LLM 打一個情感強度/重要性分數；高的更容易被想起。

**另外兩個常被忽略但關鍵：**
- **去重 / 多樣性**：別每次都撈同一段回憶。用 MMR 或對近期已用過的記憶加懲罰。
- **遺忘是 feature**：定期衰減、把舊記憶合併成摘要，而非無限堆積。

**起手式（Phase 2）**：先做「relevance + recency + importance」baseline，撈 top-k 直接注入，不加 re-ranker、不加 query 改寫。跑起來看加奈回憶對不對味，再針對性補。**真正吃時間的是調那三項權重，只能靠對話實測去感覺。**

---

## 5. 三個核心問題與對策

### 問題一：沒有複利，瀏覽不變成思考燃料
**v1 考古實證**：arXiv 瀏覽只有第一週 11 筆就停擺；her_reaction 全是 30 字敷衍句、沒有一筆連回她的論文題目；且 Reflect-Evolve 的 prompt **明文排除瀏覽內容**——perceive→think→act 迴路是設計上就斷的。全專案唯一有正循環的是 `thesis.md`：heartbeat 會 append 工作記錄、對話會注入現況，讀寫累積。
**對策（Phase 4 · knowledge 模組）**：把 thesis.md 的讀寫累積模式**推廣成通用機制**——給加奈針對在乎的主題維護一份會演進的研究筆記（`knowledge_note` 表，種子從 `characters/<id>/notes/` import）。每次瀏覽不是「摘要存檔」，而是拿新讀到的去**更新**這份筆記——我現在懂了什麼、跟之前衝突在哪、還卡在哪。整合進既有理解，而非並排堆放（reflection 樹的精神）。**反教訓寫死：瀏覽內容必須進 reflect prompt**。
**降階目標**：先做到「她對某主題的理解會隨時間改變，講得出『我之前以為X，後來覺得不是』」。寫論文當遠期里程碑。

### 問題二：她沒有自己的生活
**對策（Phase 3 · life 模組）**：把「activity=lab」這種標籤換成**每日事件生成器**——每天生出幾件具體、帶情緒殘留、**有後續**的小事（跑不動的 baseline、挖到的歌、跟學長的對話）。關鍵是**連續性與後果**（昨天壞的冷氣、今天修好的 bug、逼近的 deadline），有連續性才像「生活」。這些事件同時是對話燃料，與問題一的複利相接。
**深水版（遠期）**：多角色世界——室友/學長/指導教授為有持久小狀態的 agent，幕後互動產生真實事件（Generative Agents 的 Smallville）。先做輕量版，跑順了再升級。

### 問題三：語氣像人 / 個性
**評估**：泛角色 benchmark（CharacterEval 中文、RPEval、RoleBench）只能幫選底模型，**測不出「像不像加奈」**。加奈對不對味靠**自訂 rubric**（短句、無 AI 腔、彆扭反差…）+ LLM-as-judge + 真人 A/B。長期看 XiaoIce 的 CPS（每段對話平均輪數）這種行為信號最實在。
**讓模型真的變（Phase 5）**，階梯如下：
1. **SFT / LoRA（QLoRA）** — 蒐「理想加奈回覆」資料集（手寫 + 強模型蒸餾），把語氣烤進權重。12GB 跑得動。最務實的第一步。
2. **DPO（偏好微調）** — 有「比較像/比較不像」成對資料時，比 PPO 簡單穩定太多，直接優化主觀偏好。**個性這種目標的甜蜜點。**
3. **PPO** — 需要「加奈度」reward model，主觀風格極難寫成純量 reward；要建 reward model 不如直接 DPO。**起步不建議碰**，除非未來有穩健 reward 信號。

> 訓練天然排最後：要先有跑起來的 bot 產生並篩選對話資料，那才是 LoRA/DPO 的燃料。

---

## 6. 分階段路線圖

每個 phase 都能獨立跑起來並驗收。順序刻意把「架構能解的」放前面，「訓練」放最後。

### Phase 0 — 新骨架地基 ✅
- 建四層目錄結構、`config`、`llm_client`（本地 provider + 結構化輸出）、`repository`（aiosqlite + Pydantic model + 寫入序列化）、`embeddings`。
- 接 `.env` 既有 Discord / Threads key。
- **完成標準**：能用本地 Qwen 回一則 DM；DB 讀寫走型別層；無 `database locked`。

### Phase 0.5 — 模組化重構 ✅
- **角色包資料化**：人設從硬編碼抽成 `characters/kana/`（character.yaml + core/speech/never/backstory/tastes + notes/），`load_character` 載入、`PersonaPromptBuilder` 組裝（靜態前綴快取 + 動態段 + never 壓陣；`extra_sections` 是 Phase 2+ 的注入口）。
- **adapter 抽象**：`ChatAdapter` / `PostingAdapter` Protocol；Discord 改類別實作；新增 CLI adapter（零憑證調人格）；main 改 config 驅動選 adapter。
- **多角色 ready 的資料層**：schema 全表帶 `character_id`（`Repositories.create(path, character_id)` 建構時綁定，domain 呼叫端零負擔）；user_id 一律 `channel:id` 命名空間。
- **完成標準（已驗收）**：`ADAPTER=cli python -m kana` 不需 Discord token 可對話；引擎 .py grep 不到人設文字；角色隔離與命名空間有測試背書（25 測試綠）。

### Phase 1 — 對話品質 + 角色深化 🔄（機制完成，語氣迭代進行中）
- ✅ 對話節奏：`domain/pacing.py` 純函式決策（log-normal 延遲、回覆拆條、緩衝窗口），adapter 執行（Discord：緩衝合併＋typing＋間隔送出；CLI：直印不延遲）。handler 契約改為 `InboundMessage → ReplyPlan`。
- ✅ 關係演化：`domain/relationship.py`——Ollama JSON schema 結構化輸出 + `EvolutionResult` Pydantic 淨化層（list 逐項強制字串、delta 夾範圍——v1 的 dict 混入 list 死因的直接對策）；known_facts 去重＋上限 30（遺忘是 feature）；對話摘要寫入 episodic memory（Phase 2 檢索資料從此開始累積）。
- ✅ 背景故事擴寫：backstory.md 已是傳記（台南五金行、高中被排擠學會不動聲色、失眠期撞到 ZUTOMAYO、阿禹/小霈/妤婷人際網——Phase 3 生活事件的現成配角名單）。
- 🔄 語氣迭代：CLI 實測已修三輪（主詞混淆的事實抽取、假承諾句式、括號舞台指示、編造歌名→tastes.md 錨定真實曲目清單）；持續用 `python -m kana cli` 迭代。
- **v1 的承諾抽取（todo_commitments）確定不做**：實測效果不好。never.md 反向處理：她不說做不到的承諾。
- **完成標準**：DM 對話順暢、語氣大致對味；delay/關係抽取可單元測試（✅ 45 測試綠）；驗收工具是 CLI adapter。

### Phase 2 — 檢索式記憶 ✅
- `domain/memory.py`：`MemoryService.remember`（寫入＋bge-m3 向量化）/ `recall`（三項加權：w_rel·cosine + w_rec·半衰期衰減 + w_imp·importance − 冷卻懲罰）。權重全收在 config（MEMORY_W_* 等），調味靠實測。
- sqlite-vec `vec0` 虛擬表（cosine metric，rowid 對應 memory_episodic.id），DDL 在 db.py——extension 載入失敗時優雅退化為 recency+importance，不擋啟動。
- 防跳針：`last_recalled_at` 冷卻懲罰（剛想起的事 6 小時內降權）；太新的記憶（<90 分鐘）不撈——還在對話歷史視窗裡。
- 檢索範圍：她自己的記憶（user_id=NULL）＋與這個人的記憶——**別人的對話不會洩漏**（有測試背書）。
- 對話摘要由關係演化寫入時就向量化，檢索資料隨對話自動累積。
- **已驗收**：清空 message_log 後只說「我家那隻又拆家了」，她從向量記憶答出「麻糬又在搞破壞啊？柴犬真的會這樣嗎」。
- 未做（等實測需要再上）：MMR 多樣性、記憶合併摘要（遺忘壓縮）、re-ranker。

### Phase 3 — 生活（解問題二·輕量版）
- 每日事件生成器：具體、帶情緒、有連續性的微事件，寫入 memory 並成為對話燃料。
- affect 模組：情緒/體力連續、由事件推一把 + 自然衰減（取代每 30 分鐘 LLM 重擲；v1 實證：546 筆記憶裡 ~500 筆是心跳流水帳，狀態流水帳不准再進 memory）。
- life-plan：早上生成當日意圖，心跳推進而非重擲。
- 主動訊息走 `ChatAdapter.send`，不直接碰 discord。
- **完成標準**：朋友能感覺「她有在過日子」；對話裡自然冒出她的生活細節且前後連貫。

### Phase 4 — 會演進的主題理解（解問題一）
- knowledge 模組：`knowledge_note` 表（character_id, topic, content, updated_at）+ 改寫歷史；種子從 `characters/<id>/notes/` import（thesis.md 已就位）。
- 迴路明文：**perceive**（瀏覽/事件）→ **think**（LLM 拿舊筆記＋新素材整合改寫，保留「我之前以為X」的痕跡）→ **act**（筆記現況經 `extra_sections` 注入對話、觸發主動訊息）。瀏覽內容必須進 reflect prompt。
- 自主瀏覽路由綁回 dynamic_interests。
- **完成標準**：她講得出對某主題理解的「變化」；主動性綁到真實的著迷/未解念頭。

### Phase 5 — 讓模型真的變（解問題三·根本）
- 用前面累積的對話資料做 LoRA SFT；再進 DPO。v1 的 `threads_style.md` 真人文風馴化紀錄是現成的訓練/偏好資料。
- 建自訂評估 rubric + 真人 A/B 流程。
- **完成標準**：不靠超長 prompt，模型本身的語氣就更像加奈。

### 遠期升級（不排期）
- Threads `PostingAdapter` 掛回（介面已在 Phase 0.5 定義；等生活/知識模組成熟，她發的文才有真實生活可寫）。
- 多角色同時運行（架構已 ready：開第二個 `Repositories` 實例 + 第二個角色包即可）。
- AI 角色互聊沙盒（朋友建議的「兩個角色碰撞思考」：一個 ChatAdapter 對接兩個角色實例）。
- 多角色互動世界（問題二·深水版）。
- 寫論文能力（問題一·遠期里程碑）。
- audio.py 重新掛回（含 VRAM 錯開；v1 實測音訊分析＋長文生成這條線品質很好）。
- 視規模決定是否上 Postgres。

---

## 7. 參考論文（對應模組）

| 論文 | 對應 | 連結 |
|------|------|------|
| Generative Agents（Park 2023）**必讀** | 記憶評分、reflection、life-plan 的骨架 | arXiv 2304.03442 |
| XiaoIce（Zhou 2020） | 陪伴型 bot 系統設計、EQ/IQ、CPS 長期指標、affect | arXiv 1812.08989 |
| Structured Personality Control（2026） | Cognition/Emotion/Character Growth 回饋迴圈 ≈ Reflect-Evolve | arXiv 2601.10025 |
| MemoryBank | 艾賓浩斯遺忘曲線 ≈ 記憶衰減 | — |
| A-Mem / Mem0 | 可落地長期記憶系統 | arXiv 2502.12110 / 2504.19413 |
| CharacterEval | **中文**角色扮演評測（一致性/行為/吸引力） | — |
| RoleLLM / Character-LLM | 角色側寫建構與角色微調（→ LoRA） | — |
| Memory-Driven Role-Playing（2026） | 角色扮演時的記憶/人格調用 | arXiv 2603.19313 |
| Spontaneous Emergence of Agent Individuality | 多角色互動下情緒位移、人格浮現（遠期） | arXiv 2411.03252 |

持續追蹤：清華 Awesome-Memory-for-Agents、AGI-Edgerunners/LLM-Agents-Papers。

---

## 8. 保留 / 捨棄

- **捨棄**：全部舊 code、舊 `data/kana.db`、`src/kana.db`（0-byte 殘檔）、各 `fix_*.py` / `test_*.py` 一次性腳本。承諾消化 pipeline（todo_commitments）——實測效果不好，v2 不做。
- **保留**：`.env` 裡的 Discord token、Threads access token / user id、admin/owner id。其餘金鑰視 Phase 5 是否用雲再定。
- **v1 內容資產遷移對照表**（備份在 `kana_v1_backup_2026-06-18.zip`）：

| v1 資產 | 去向 | 狀態 |
|---------|------|------|
| `persona.md`（人設） | `characters/kana/core.md` + `speech.md` + `backstory.md` | ✅ 已搬 |
| `claude_client.py` 的 PERSONA_BASE「絕對不做」清單（調校精華） | `characters/kana/never.md` | ✅ 已搬 |
| `media_taste.md`（~100 部作品評分） | 精華 → `characters/kana/tastes.md`；完整清單 → 日後 media_library 表 | ✅ 精華已搬 |
| `data/thesis.md`（論文進度，唯一有正循環的生活線） | `characters/kana/notes/thesis.md`（Phase 4 knowledge 種子） | ✅ 已搬 |
| ZUTOMAYO 策展資料（threads.py 內 9 首歌 + ACAね 生平） | tastes.md 收精神；完整資料等 Threads 掛回再搬 | 部分 |
| `data/threads_style.md`（真人文風馴化紀錄） | **Phase 5 微調/偏好資料**，原檔保留於備份 | 待 Phase 5 |
| `memory_system.md` / `schedule.md`（設計論述） | 設計思想參考（延遲分布、關係階段行為差異） | 參考用 |

---

## 9. 待決定 / 開放問題

- 對話模型：先全本地 Qwen3-14B 實測，若細膩度不足再決定是否 chat 走混合。
- 記憶三項權重初值：上線後靠對話手調。
- 生活事件生成的頻率與「配角」名單：Phase 3 開始時定。
- 微調資料來源比例（手寫 vs 強模型蒸餾）：Phase 5 前定。
