# Functional tasks

## LB-20261113-01 — LazyBuddy modular application

Status: independent source, packaging, API and integration validated. Owner: Leager / Windows Codex. Updated: 2026-11-14. Branch: main. Whole-product acceptance is tracked in LazyBuddyDev/LazyBuddy TASKS.md; this is the same functional requirement, not a phase task.

- `[√]` Own hongguo source, API, manifests, build/package scripts, tests and CI without desktop source imports.
- `[√]` Independently build packages and verify external host/API integration.
- `[√]` Publish under LazyBuddyDev/hongguo-service, MIT copyright 2026 Leager, preserving third-party terms.
- `[√]` Start from one parentless initial commit, per user request; old Git branches/tags are removed and a local ignored recovery bundle is kept.
- `[x]` Final whole-product acceptance and signed binary publication; Hongguo real-account permission/AV checks need the user's QR scan, and real writes need separate authorization.

Evidence: news core 7 and HTTP boundary 2 tests; Hongguo Python 80, search 5 (one real-network case ignored), decoder protocol 4 and Go resolver passed. Independent package health/install/remove/HEIC and external-host synthetic playback passed. Test only the affected layer for ordinary changes. CI runs independently in this repository.

Next: check the initial commit's Actions result, complete required real-account acceptance and prepare separately authorized signed publication. Do not archive the whole requirement prematurely.

2026-11-14, supporting host UI task LB-20261114-04: codex/lazybuddy-browser-video adds playback resource sessions, Origin/Host/token-bound CORS Range reads, suspend/resume and generation-bound checkpoints/close. Browser output creates no decoder; cancelled upstream reads no longer populate an inactive cache. 37 affected units pass. External fixture package → actual Tauri WebView decodes synthetic H.264 and H.265/AAC, paused frame mediaTime=3.1s, hidden resource rejects reads and src is unloaded, resume stays paused at 3.1s, settings release the old endpoint and normal exit finishes. The production 0.2.0 candidate builds with only python-runtime dependency; real packaged entry health passes, no media-runtime directory is staged. Unchanged search binary reused from the prior package, hash b5adbc861409f7dc1b6f355ffb22e6efbf0b623e70e93e87935babb53c1c891b. No real account/media permission or AV-sync claim; no signed catalog or binary publication. Full host business UI/progress wiring and real-stream validation remain pending; see docs/browser-playback.md.
