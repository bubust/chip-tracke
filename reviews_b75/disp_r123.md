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
Round 2 dispositions (coordinator): all 4 ACCEPTED.
- R2 G-F1 LWC timezone: API sends UTC epoch; LWC timeFormatter/tickMarkFormatter use Intl Asia/Taipei (§4.1).
- R2 G-F2 TX session boundaries incl. Friday night -> Saturday 05:05, Sunday/Monday-early closed (§5).
- R2 G-F3 backfill only trading days present in fut_daily (FinMind confirms open); 404/empty recorded, not retried same day (§3.4).
- R2 G-F4 polarity stored per factor; direction = sign(state) * polarity (§6.2).
- R3 low items accepted: Yahoo ^TWII 5m fallback at 16:30 when today's TWII bars5 incomplete (§3.4); trading date from cnyes daily latest bar / FinMind dates, never inferred (§5).
