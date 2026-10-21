Round 1 (Groq only; Gemini 503). Dispositions:
- F1 global RLock deadlock/starvation: PARTIALLY ACCEPTED. heavy() wraps only top-level job entry points (never code run on worker threads), RLock makes same-thread nesting safe (refresh_all -> tab step), wait timeout 60 min then skip+log. Per-job locks rejected: the whole point is to serialise memory peaks on a 512MB machine.
- F2 fallback to full r.json() would re-OOM: ACCEPTED. No full-load fallback; on ijson failure the ingest is marked failed and old contracts stay; temp file deleted in finally; 200MB download cap.
- F3 numeric robustness of erf/Brent: ACCEPTED as tests (grid incl. tails |x|<=8, deep ITM/OTM, near-expiry, no-root cases, compared with scipy). Keeping scipy as runtime fallback REJECTED (defeats the 54MB saving).
- F4 crash loop: ACCEPTED partially: max 2 attempts per scan day persisted in catchup.json (already), 2nd attempt delayed to 10 min after boot; refresh-all step skipped after 2 interruptions.
- F5 /healthz payload: already minimal ("ok"); details only in /api/system/health.
- F6 container memory integration test: REJECTED (Windows dev box cannot emulate a cgroup); replaced by local peak measurement of the real jobs + production job-log peak RSS after deploy.
- F7 swap on free tier: Fly Machines support swap_size_mb on all paid-usage machines (this app is billed usage, not a free tier); will verify SwapTotal in /proc/meminfo after deploy.
- F8 thundering herd: single-flight lock + serve-stale-while-refresh already prevents bursts; library not needed.
Scope expanded per user (sections E, P13-P16): K-line monthly-slope pane removed, marker autoscale margins capped, lazy iframes, batched TDCC trends, front-end request de-dup, prewarm.
