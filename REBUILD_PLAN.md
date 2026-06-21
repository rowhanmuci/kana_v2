# 加奈 v2 — 重塑藍圖

> 本文件是整個重塑的設計地圖。先讀「核心原則」與「新架構」理解大方向，再照「分階段路線圖」一步步走。
> 舊 code 與舊 DB 全部捨棄，只保留 `.env` 裡的 Discord / Threads 憑證。

---

## 0. 為什麼重塑

兩個目標，順位如下：

1. **角色更真實** — 讓加奈像個有生活、會累積、有個性的人，而不是貼著狀態標籤上網的機器。
2. **穩定性** — 根治舊版反覆出現的型別錯誤、`database locked`、JSON 解析失敗、以及因 API 餘額/限流導致的停擺。

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

---

## 2. 新架構骨架

依賴方向由上往下，下層不認識上層。

```
① Adapters（純 I/O，可替換）
   discord_adapter · threads_adapter · admin_adapter
        ↓
② Domain Services（流程編排，無 I/O 細節）
   conversation · proactive · life · social
        ↓
③ Cognitive Core（加奈的「腦」——真實感的關鍵，不依賴 Discord，可單獨測試）
   memory（episodic + 檢索） · affect（連續情緒/體力）
   · life-plan（每日行程/事件，心跳推進） · knowledge（會演進的主題理解）
   · persona（組裝 + 演化）
        ↓
④ Infra（被所有層共用）
   llm_client（local/cloud 可換 provider + 結構化輸出）
   · repository（aiosqlite + Pydantic 型別層）
   · embeddings（本地） · config · scheduler
```

與舊版最大差異：把糾纏在 `bot.py` / `memory.py` 的邏輯抽出成獨立的 **Cognitive Core**，四個真實感槓桿全落在這層、彼此解耦、可單元測試。

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
**對策（Phase 4 · knowledge 模組）**：給加奈針對在乎的主題維護一份**會演進的研究筆記/知識物件**，而非扁平記憶列。每次瀏覽不是「摘要存檔」，而是拿新讀到的去**更新**這份筆記——我現在懂了什麼、跟之前衝突在哪、還卡在哪。整合進既有理解，而非並排堆放（reflection 樹的精神）。
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

### Phase 0 — 新骨架地基
- 建四層目錄結構、`config`、`llm_client`（本地 provider + 結構化輸出）、`repository`（aiosqlite + Pydantic model + 寫入序列化）、`embeddings`。
- 接 `.env` 既有 Discord / Threads key。
- **完成標準**：能用本地 Qwen 回一則 DM；DB 讀寫走型別層；無 `database locked`。

### Phase 1 — 對話核心 + 人格（prompt 層）
- conversation service、persona 組裝（取代 140 行字串拼接）、延遲邏輯、message log。
- 把人格用 prompt + 選模型調到「可接受」。
- **完成標準**：DM 對話順暢、語氣大致對味、可單元測試 delay/persona 組裝。

### Phase 2 — 檢索式記憶
- episodic memory + sqlite-vec，三項加權檢索、去重、衰減。
- **完成標準**：她在對的時機想起對的舊事，而不是只看最近幾筆；權重可調。

### Phase 3 — 生活（解問題二·輕量版）
- 每日事件生成器：具體、帶情緒、有連續性的微事件，寫入 memory 並成為對話燃料。
- affect 模組：情緒/體力連續、由事件推一把 + 自然衰減（取代每 30 分鐘 LLM 重擲）。
- life-plan：早上生成當日意圖，心跳推進而非重擲。
- **完成標準**：朋友能感覺「她有在過日子」；對話裡自然冒出她的生活細節且前後連貫。

### Phase 4 — 會演進的主題理解（解問題一）
- knowledge 模組：針對在乎的主題維護可改寫的研究筆記；瀏覽 → 整合更新而非堆放。
- 自主瀏覽路由綁回 dynamic_interests。
- **完成標準**：她講得出對某主題理解的「變化」；主動性綁到真實的著迷/未解念頭。

### Phase 5 — 讓模型真的變（解問題三·根本）
- 用前面累積的對話資料做 LoRA SFT；再進 DPO。
- 建自訂評估 rubric + 真人 A/B 流程。
- **完成標準**：不靠超長 prompt，模型本身的語氣就更像加奈。

### 遠期升級（不排期）
- 多角色互動世界（問題二·深水版）。
- 寫論文能力（問題一·遠期里程碑）。
- audio.py 重新掛回（含 VRAM 錯開）。
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

- **捨棄**：全部舊 code、舊 `data/kana.db`、`src/kana.db`（0-byte 殘檔）、各 `fix_*.py` / `test_*.py` 一次性腳本。
- **保留**：`.env` 裡的 Discord token、Threads access token / user id、admin/owner id。其餘金鑰視 Phase 5 是否用雲再定。
- **可參考不照搬**：`persona.md`、`media_taste.md` 等設定文件的「內容」（加奈是誰、看過什麼）可餵進新 persona 與 media 資料；但組裝方式重做。

---

## 9. 待決定 / 開放問題

- 對話模型：先全本地 Qwen3-14B 實測，若細膩度不足再決定是否 chat 走混合。
- 記憶三項權重初值：上線後靠對話手調。
- 生活事件生成的頻率與「配角」名單：Phase 3 開始時定。
- 微調資料來源比例（手寫 vs 強模型蒸餾）：Phase 5 前定。
