# PLAN-B76 審查紀錄（/claudex-loop 延續）

- 日期：2026-10-21；角色同 B75：主持／實作＝Claude Code（Opus 5.5），計畫審查與程式檢查＝Gemini＋Groq（不用 Codex）
- 用戶決定：4 個週期取代三模式＋多週期一覽；條件式操作建議（規則）；融資近 10 天；總經狀態／操作建議／之前研究的訊號上移
- 授權：同 B75（測試 → 推 main → 自動部署）；計畫審查最多 3 輪（小批次）、程式檢查 2 次

## 計畫第 1 輪（原始輸出 reviews_b75/b76_plan_r1.json）

### Gemini gemini-3-flash-preview：APPROVED
The plan for B76 is technically sound and maintains backward compatibility with B75. It correctly addresses the user's request for timeframe-specific analysis and introduces a more granular advice engine. Key strengths include the mapping of legacy mode keys to timeframes and the explicit acknowledgement of low statistical confidence for the 30-minute timeframe research.
- [medium] F1 §3 Research R-I30/R-K30: The calibration target for 30m (9 bars) is based on the TWII 4.5-hour session. For TX (Taiwan Futures) which includes a night session, 9 bars represent only ~4.5 hours of a ~19-hour trading cycle, potentially leading to 'over-sensitive' wave counting compared to the Daily/Weekly counterparts. → Adjust the 30m calibration logic in `calibrate_intraday.py` to differentiate between TWII (target ~9 bars) and TX (target ~38 bars) to maintain the '1-day swing' logic across symbols.
- [medium] F2 §4 Conditional Position-Sizing: The advice engine uses 'Upper/Lower half' of a range (e.g., half of 70-100% is 85-100%). However, if the market regime is 'Extreme Risk' (0-20%), the 'Upper half' (10-20%) still represents an 80-90% reduction from base, which might be ignored by users if the UI doesn't clearly display the percentage range. → The advice engine should explicitly return the calculated numeric range (e.g., '建議部位: 10-20%') alongside the prose to avoid ambiguity.
- [low] F3 §2 Backend wave/intraday.py: The current `intraday.py` implementation explicitly uses the 60m theta for 30m bars ('30 分 K 用上一根收完的 60 分 K 的 θ'). The PLAN-B76 aims to replace this with an independent m30. → Ensure the `analyze` function in `intraday.py` is refactored to accept a timeframe-specific theta calculation rather than hardcoding the 60m dependency.
- [low] F4 §5 Front-end: Moving Macro/Advice to the top is beneficial for mobile users, but 'Multi-timeframe Ladder' and 'Advice' might conflict in space on small screens. → Use a collapsible 'Warning/Signal' banner for the Advice engine risks if more than 3 risk factors are active simultaneously.

### Groq openai/gpt-oss-120b：REVISE
The plan is comprehensive and respects existing B75 logic, but there are material concerns around look‑ahead safety, statistical honesty for the very short 30 m sample, deterministic handling of missing data in the advice engine, and explicit backward‑compatibility mapping for snapshot keys and localStorage values.
- [high] F1 3. 研究 R‑I30／R‑K30: Calibration of the 30 m θ and key‑level thresholds uses the full 40‑day window to pick the best m30 value, but the selection criteria (average wave length closest to 1 day) implicitly looks at the *future* of the calibration window (e.g., wave counts that span the end of the window). This creates a subtle look‑ahead bias when the same parameters are later applied to live data. → Restrict the calibration to only use data that is fully known at each point (e.g., use a rolling window that ends 1 day before the evaluation period) and store the chosen m30 per day. In the production snapshot, use the parameter that was selected on the previous day only.
- [high] F2 4. 條件式操作建議: The advice engine does not define deterministic fall‑backs when required inputs are missing (e.g., regime tags, multi‑timeframe direction, or key‑level objects). The current description says “沒有就寫‘沒有特別警訊’”, but the code may still attempt to access undefined fields, causing runtime errors. → Implement explicit guard clauses in `wave/advice.py` that return a minimal advice object with `hold_range: null` and an empty `conditions` array when any required input is absent. Document the fallback behavior in the function docstring.
- [medium] F3 2. 後端（wave/）: The new snapshot fields (`levels.m30`, `key.m30`, `waves.intra30`) are added without versioning. Clients that only understand B75 may ignore unknown keys, but older UI code that iterates over snapshot keys could break if it assumes a fixed set. → Add a `snapshot_version` field (e.g., `2`) and update the frontend to filter keys based on the version it supports. Also, ensure that any generic loops over `snapshot` keys skip unknown prefixes safely.
- [medium] F4 1. 驗收條件 – 多週期一覽: The UI spec states that clicking a row switches the timeframe, but does not specify how the state is persisted across page reloads or when the user switches symbols. → Persist the selected timeframe in `localStorage.wv_tf` and, on symbol change, retain the current `wv_tf` value. Add a unit test in `tests_ui/b76_ui.py` that verifies the timeframe remains after a symbol switch.
- [low] F5 3. 研究 R‑I30／R‑K30 – 統計力: The plan mentions “樣本只有 60 天（加權）／30 天（台指期），統計力很低” but does not require a disclaimer in the UI. → Add a small footnote under the 30 m analysis card: “基於短期樣本，僅供參考，勿作為唯一決策依據”。
- [low] F6 5. 前端 – UI 排列: The new “操作建議” block is placed above the K 線圖, but the existing CSS grid may not have enough vertical space on mobile, causing overflow. → Introduce a collapsible accordion for the advice block on screens < 768 px and add a UI test that checks the block is hidden/collapsible on mobile viewport.

### 處置
B76 round-1 dispositions:
Gemini F1 (TX 30m target 38 bars): REJECTED - design principle is ~9 bars per leg on every chart; TX uses the same m as B75 did for 60m (pre-registered).
Gemini F2 numeric range: ACCEPTED (§4.5 range object). Gemini F3 tf-specific theta: ACCEPTED (planned). Gemini F4 risk overflow: ACCEPTED (max 3 risks + 'N more').
Groq F1 calibration look-ahead: REJECTED - parameter chosen once on a past window and fixed; live theta uses only past ATR (same as B74/B75).
Groq F2 advice fallbacks: ACCEPTED (§4.6). Groq F3 snapshot version: ACCEPTED as v:76 (frontend has no generic key iteration).
Groq F4 tf persistence: ACCEPTED (+UI test). Groq F5 30m disclaimer: ACCEPTED. Groq F6 collapse advice on mobile: REJECTED (user asked to see it on top; UI test checks no horizontal overflow).

## 計畫第 2 輪（原始輸出 reviews_b75/b76_plan_r2.json）

### Gemini gemini-3-flash-preview：APPROVED
The plan successfully integrates per-timeframe analysis (30m to Weekly) and the new conditional position-sizing engine. It adheres to all previous round dispositions, including the v:76 versioning, risk overflow handling, and the 9-bar calibration target for the 30m timeframe. The layout reorganization places macro/advice at the top as requested while maintaining technical consistency across timeframes.
- [low] F1 4.3: Proximity of conditional levels. → If the 1st and 2nd resistance/support levels are extremely close (e.g., < 0.2% apart), the advice logic should deduplicate or merge the conditions to avoid redundant 'Scale up' or 'Scale down' instructions.
- [low] F2 2.0: Mapping of legacy keys. → Ensure that the mapping from 'ultra' to 60m and 'short' to 1d is explicitly documented in the code to prevent future confusion when 'ultra' might be misinterpreted as 30m.

### Groq openai/gpt-oss-120b：APPROVED
The PLAN-B76 addresses all previously rejected items: 30‑minute wave calibration now targets ~9 bars per leg, theta is computed solely from past ATR data, and the advice UI is placed on top with no horizontal overflow. Snapshot extensions, advice format, risk overflow handling, and UI layout follow the accepted specifications. No critical defects remain.
- [low] S1 3. 研究 R-I30: The lower‑bound variable for theta is referenced as "下限30" without explicit definition; reviewers may need clarification of its numeric value and unit. → Add a brief comment or constant definition (e.g., LOWER_THETA = 0.4%) and reference it in the code to avoid ambiguity.
- [low] S2 6. 驗證: UI test for mobile overflow (Groq F6) is mentioned but not explicitly listed among the test cases. → Include an explicit pytest‑ui test that asserts the advice panel width does not exceed the viewport on mobile devices.

### 第 2 輪處置
- 兩位都核准：PLAN-B76.md SHA256 bb090921382ab6eb436ff3e5f93ca9138c5ba7bd38e5b7b07472db7f6d1a4a26
- 低優先建議實作時做、計畫不再改：條件價位差 < 0.2% 合併、舊鍵（ultra＝60 分、short＝日 K、swing＝週 K）在程式註明、30 分 K 下限常數 0.4%、手機寬度測試

## 實作（builder＝Claude，分支 b76，起點 43f5c4f）
- 研究 research/futures/r30.py：R-I30 m30＝2（校準 2026-07-27～09-18 平均每段 1.05 天）；R-K30 選 K3（距離中位數 1.2%、90 百分位 3.3% 超過 2% → 依規則取最接近範圍中點），延續率跟對照差不多（不顯著）；樣本短照實標
- 新：wave/advice.py（條件式操作建議）、wave/plain.py（白話，跟前端同一套）；改：intraday.py（analyze_tf：30／60 分各自 θ）、levels.build_ultra（win／k3_look／週期名稱）、engine INTRA30、service（levels.m30／key.m30／waves.intra30、ladder、ladder_text、advice、context.oh、v:76、台指期頁也算 open_ref）、composite.margin_block last10、panel（30 分 K、多週期、操作建議、m30 價位白名單）、router（推播「💡 操作」一行）
- 前端：四個週期按鈕取代三模式＋K 線週期按鈕；💡 操作建議（總經狀態搬上來＋細部解讀）＋🧭 之前研究的訊號（展開）；📶 多週期一覽（點一列切週期）；融資卡預設展開＋近 10 天表
- 實作時的低優先項：條件 0.2% 內合併、舊鍵對照寫在 service.TF_KEYS 與 wave.js TF、30 分 K 下限常數 0.4%（engine.INTRA30）、手機寬度測試
- 驗證：pytest 365 passed（新 11）；tests_ui/b76_ui.py 全過（加權／台指期 × 4 週期 0 JS 錯誤、劇本／撐壓／標題跟著週期換、一覽點列切換、切商品與重新整理保留週期、舊 wv_mode 對應、融資 10 列、舊按鈕都拿掉、390 寬無橫向捲動）

### 程式檢查（後端，新的審查呼叫）Gemini gemini-3-flash-preview：APPROVED
The implementation of B76 successfully establishes per-timeframe analysis independence, specifically calibrating 30m K with its own theta and sensitivity parameters (m30). The advice engine accurately implements the multi-period direction rules, exposure halving logic, and overheating caps defined in the plan. Legacy key mappings (ultra/short/swing) are preserved for push-notification compatibility while being correctly mapped to the new ladder structure. Risk warnings and margin history also meet the 10-day requirement with proper sorting.
- [low] F1 wave/advice.py: Condition merging keeps the earlier price in the sorted list during label concatenation. → Currently acceptable as 0.2% is a negligible distance, but keep in mind that the displayed price might be slightly lower than the 'swing' target if it was merged into a 'short' target.

### 程式檢查（前端，新的審查呼叫）Gemini gemini-3-flash-preview：APPROVED
The implementation of the 4-timeframe multi-period analysis, conditional advice system, and layout restructuring strictly follows the B76 plan. The migration logic for timeframe selection ensures backward compatibility with the legacy 'wv_mode' storage. XSS protection is consistently applied via the 'esc' helper for all dynamic data, and the multi-timeframe mapping accurately addresses the new snapshot keys (m30, ultra, short, swing).

### 程式檢查（advice.py（Groq 去註解），新的審查呼叫）Groq openai/gpt-oss-120b：REVISE
The implementation deviates from the specification in key logical checks and fails to sanitize dynamic output, creating functional and security issues.
- [high] F1 advice.py: All‑up / all‑down condition uses "len(ds) >= 2" instead of requiring all three time‑frames (60m, 1d, 1wk) to be present and equal. This triggers upper/lower‑half exposure incorrectly when only two directions are available, violating the spec. → Change the condition to require exactly three aligned directions: "if len(ds) == 3 and all(d == 1 for d in ds):" and similarly for the down case.
- [high] F2 advice.py: Dynamic strings inserted into the output are not passed through an escaping function (_esc) as required by the security policy, opening XSS vectors for untrusted data (e.g., regime label, key level labels, risk messages). → Import the project‑wide escaping helper (e.g., from .utils import _esc) and wrap every interpolated external value: _esc(regime), _esc(k1['kind']), _esc(risk_msg), etc. Ensure all user‑controlled data is escaped before inclusion in the response.

### 處置
- Gemini 後端 F1（合併時顯示較近的價位）：接受現狀（差 < 0.2%）
- Groq F1「兩個方向就判定一致」：不成立——計畫 §4-6 保底規則「某週期沒有方向 → 只看有的」，且至少 2 個
- Groq F2「後端要跳脫字串」：不成立——後端回 JSON，畫面輸出時跳脫（wave.js esc()、推播 html.escape），Gemini 前端檢查確認全部有跳脫
## 結論
- 計畫：Gemini、Groq 第 2 輪都核准（SHA bb0909…）
- 程式：Gemini 後端／前端核准；Groq advice.py 2 點實測／對照計畫不成立，沒有要修的
