Round 1 dispositions (coordinator):
Gemini:
- G-F1 roll distortion in night return: ACCEPTED. §3.2: night rows store ref_close = SAME contract's previous day-session close; night_ret uses it. Live uses cnyes reference price.
- G-F2 chip publication timing: ACCEPTED (modified). Post-close factors F2-F7: (a) next-day target = r(T+1) residual after removing what night return F1(T+1) explains (incremental value beyond night session); (b) 5/20-day targets start from Open(T+1).
- G-F3 cache keyed by symbol: ACCEPTED (§5).
- G-F4 session detection per symbol: ACCEPTED (§5, D.in_session(sym)).
- G-F5 gap beta vs r1 beta: ACCEPTED (§6.1/6.2).
- G-F6 persistent volume / single pass: ACCEPTED as clarification (§3.4/3.5; volume already mounted at /app/chip_data).
- G-F7 option OI amount: ACCEPTED (§3.3).
Groq:
- Q-F1 k3 confirmation look-ahead: ACCEPTED as clarification (§3.2: only closed bars confirm pivots; partial bar = price only). Already k3 needs i+3 close.
- Q-F2 multiple testing in key-level selection: ACCEPTED: BH across the 9 candidate x mode tests; bands/candidates pre-registered, not tuned.
- Q-F3 roll rule + price back-adjustment: REJECTED. Back-adjusting would make support/resistance prices non-tradable historical prices; max-volume roll is deterministic and contract is stored per row. Research night-return distortion handled by G-F1.
- Q-F4 timestamps: ACCEPTED as tests; bars5.ts is epoch seconds (UTC by definition), Taipei conversion only at aggregation/display.
- Q-F5 memory monitor abort: REJECTED (sequential single-file streaming with a lock is sufficient; peak memory is the per-file dict of ~2,000 5-min bars).
- Q-F6 job retry/alerts: PARTIAL: every source uses mark() (UI shows failing sources), cnyes retry once, missed days backfilled from TAIFEX zips at 16:30. No Telegram alerts (avoid spam).
- Q-F7 terminology/significance badge: ALREADY in plan (§2.4 plain-language text and significance wording; §7 every number has one plain line).
- Q-F8 tests: ALREADY in §11 (excerpt did not include it). 80% coverage target rejected.
