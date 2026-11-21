# Current tasks

## LB-20261115-15 — App playback empty response

Owner: Windows Codex. Updated:2026-11-21. Branch:main. Published package:0.2.15 with host1.0.10; the current update adds origin-bound media CDN redirects only. The user explicitly paused this empty-response investigation; no real-account or upstream probes were made for the preload change.
- User confirmed current Hongguo playback/auto-next works for the1.0.8 release on2026-11-21. Original specified items and the historic empty-body cause were not independently rechecked; investigation remains paused.
- Current: empty body and read failure are separate; finite HTTP metadata and safe stack locations return through API diagnostics; service writes no logs. Quality fallback and favorite covers were confirmed working by the user and are independent of this error.
- Host log21:24:14/21:24:16: series7689716417968491544 episode1 requested1080p/direct, HTTP200, declared_length0, body_bytes0, body_read_ok true, HTTP2, request ID present, Date delta0. Server reason remains unknown; duplicate CSRF cookie merging was corrected but causality is not proven.
- `[x]` Obtain verifiable protocol/session/signature evidence explaining the empty body and fix the cause or establish a documented upstream limitation.
- `[x]` Verify the original failing item after the fix; success on another item does not establish permissions or root cause.
- Package0.2.13 is public with host1.0.0; source CI and signed-catalog HTTPS install/health checks passed without real account access. The empty-response issue remains unverified and open. Do not rotate devices/accounts, expand endpoint trust or automatically retry.

## LB-20261121-02 — Complete media scheduler origin-family handling

Owner: Windows Codex. Updated:2026-11-22. Branch:main. Target:hongguo0.2.16, host remains1.0.10. Corrective delivery for the same authorized1.0.10 redirect bug.
- `[√]` Installed0.2.15 rejected original series7708575928661576766 episode40 at00:14:44: v5-reading-video-b.qznovelvod.com to an opaque vegslb node. Cause:0.2.15 trusted literal source instances instead of the numbered media origin family.
- `[√]` Initial sources still require HTTPS *.qznovelvod.com. Delegation requires numbered reading-video origin family (single-letter/cdn/cdn302 variants) and existing qualified CDN node templates. Number/letter variants no longer invent new trust boundaries.35 affected tests passed, including exact B failure replay, D/other letters, numbering, direct/proxy and rejection paths. Exact logged origin/target:0.2.15 rejects,0.2.16 accepts; nodes remain forbidden initial sources.
- `[√]` Complete final0.2.16 package built and staged in host target/packages/development/hongguo/0.2.16. Original episode40 final package decoded1920x1080,61 frames,mediaTime2s; no account/progress writes. Current successful assignment was video-a; earlier package probe observed video-d. Historical B delegated route not freshly reproduced; regression covers it.
- `[x]` Publish immutable0.2.16 module and existing-identity signed catalog, verify actual-host HTTPS module update/health/reclamation, then close this task. No new host version or host bundle replacement.
- Host evidence: tmp/verification-redirect-0.2.16. Historic empty-response investigation above remains paused and separate.
