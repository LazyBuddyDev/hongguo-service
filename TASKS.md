# Current tasks

## LB-20261115-15 — App playback empty response

Owner: Windows Codex. Updated:2026-11-21. Branch:main. Published package:0.2.16 with host1.0.10; the current update adds origin-bound media CDN redirects only. The user explicitly paused this empty-response investigation; no real-account or upstream probes were made for the preload change.
- User confirmed current Hongguo playback/auto-next works for the1.0.8 release on2026-11-21. Original specified items and the historic empty-body cause were not independently rechecked; investigation remains paused.
- Current: empty body and read failure are separate; finite HTTP metadata and safe stack locations return through API diagnostics; service writes no logs. Quality fallback and favorite covers were confirmed working by the user and are independent of this error.
- Host log21:24:14/21:24:16: series7689716417968491544 episode1 requested1080p/direct, HTTP200, declared_length0, body_bytes0, body_read_ok true, HTTP2, request ID present, Date delta0. Server reason remains unknown; duplicate CSRF cookie merging was corrected but causality is not proven.
- `[x]` Obtain verifiable protocol/session/signature evidence explaining the empty body and fix the cause or establish a documented upstream limitation.
- `[x]` Verify the original failing item after the fix; success on another item does not establish permissions or root cause.
- Package0.2.13 is public with host1.0.0; source CI and signed-catalog HTTPS install/health checks passed without real account access. The empty-response issue remains unverified and open. Do not rotate devices/accounts, expand endpoint trust or automatically retry.
