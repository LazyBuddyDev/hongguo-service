# Current tasks

## LB-20261128-02 — Diagnose playback empty body despite local signer

Windows Codex, 2026-11-28, service main b14c39b, host 1.0.11, installed hongguo 0.2.21 + signer 0.1.0.

- `[√]` User reports series 7664839801975098393 episode 60 (second season/title suffix 2), direct 1080p. Host log 21:47:22: complete HTTP/2 200, JSON content type, zero-byte body before media creation. Treat official App as playable per standing troubleshooting assumption.
- `[√]` Read-only reproduction: current 0.2.21 and prior 0.2.20 both return empty playback body for that episode. Previously verified series 7708575928661576766 episode 40 now also returns empty body under 0.2.21. Fresh signer called for catalog and playback; six signature headers generated and clocks aligned. Separate exact-device check confirms device_id/iid match saved profile. No account, device, favorites or progress writes. Sanitized evidence: host tmp/verification-empty-20261128/probe.json and confirmed-device.json.
- `[√]` Upstream PR 25 preserves Medusa on pure-Go V5 POST; current service uses native signer and fixed player GET and already includes Medusa. PR 23 changes V5 request/constants; its results do not establish a fix for this request path. No speculative patch or automatic fallback applied.
- `[x]` Obtain comparable current official request/server evidence or validate a specific upstream-compatible request change with the original identity. Empty HTTP 200 gives no verifiable rejection reason; protocol/signature/device policy hypotheses remain unconfirmed.
