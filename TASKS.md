# Current tasks

## LB-20261115-15 — App playback empty response

Owner: Windows Codex. Updated:2026-11-21. Branch:main. Published package:0.2.14 with host1.0.8; the update adds bounded next-episode preparation only. The user explicitly paused this empty-response investigation; no real-account or upstream probes were made for the preload change.
- User confirmed current Hongguo playback/auto-next works for the1.0.8 release on2026-11-21. Original specified items and the historic empty-body cause were not independently rechecked; investigation remains paused.
- Current: empty body and read failure are separate; finite HTTP metadata and safe stack locations return through API diagnostics; service writes no logs. Quality fallback and favorite covers were confirmed working by the user and are independent of this error.
- Host log21:24:14/21:24:16: series7689716417968491544 episode1 requested1080p/direct, HTTP200, declared_length0, body_bytes0, body_read_ok true, HTTP2, request ID present, Date delta0. Server reason remains unknown; duplicate CSRF cookie merging was corrected but causality is not proven.
- `[x]` Obtain verifiable protocol/session/signature evidence explaining the empty body and fix the cause or establish a documented upstream limitation.
- `[x]` Verify the original failing item after the fix; success on another item does not establish permissions or root cause.
- Package0.2.13 is public with host1.0.0; source CI and signed-catalog HTTPS install/health checks passed without real account access. The empty-response issue remains unverified and open. Do not rotate devices/accounts, expand endpoint trust or automatically retry.

## LB-20261121-02 — Intermittent media redirect rejection

Owner: Windows Codex. Updated:2026-11-21. Branch:main. Package:0.2.14. Diagnosis only, no runtime changes.
- Goal: resolve intermittent rejection on verified media redirects while preserving HTTPS and per-hop origin checks.
- `[√]` User reported series7708575928661576766 episode14,1080p/direct succeeded after two manual retries. Host log17:16:16 shows hop1 from v11-reading-videocdn302.qznovelvod.com to a host under v.smtcdns.com; another rejected chain originated at v5-reading-video-a.qznovelvod.com and targeted vegslb.com. progressive.py allowed() accepts only *.qznovelvod.com. Exact successful route is not recorded; retry success alone does not prove that route or trust.
- `[x]` Establish official media usage and narrow trust conditions for the two redirect targets. Public search did not produce authoritative evidence. Shared-CDN ownership alone is insufficient; do not broaden allowlist or add retries to hide the failure.
- `[x]` Implement verified adaptation, test direct/proxy hops and preserved Range plus rejection paths; create new immutable package and stage development bundle in host before delivery, then check original episode.
- No real-account probes, credential reads or source requests made. Historic empty-response investigation above remains paused and separate.
