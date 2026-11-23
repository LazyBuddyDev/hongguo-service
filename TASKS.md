# Current tasks

## LB-20261115-15 — Publish verified local signer playback recovery

Windows Codex, 2026-11-24, main. Candidate hongguo 0.2.20 + hongguo-signer 0.1.0, upstream signer 32d2a8c, private Java 21. User authorized full publication and confirmed native-library redistribution authorization.

- `[√]` Original account/device: episodes 40/65/66, two historical first episodes and both original episode-6 items all decoded 2 seconds. Six samples were 1920x1080; historical 7689716417968491544 episode 1 was 1280x720 under a requested 1080p preference. No account writes during playback. Evidence in host tmp/verification-release-1.0.11/media-summary.json.
- `[√]` Managed runtime authentication/startup/reaping, offline tests, isolated package install and health passed. Host sync fixes separately verified 79 readable cloud records and 7 real uploads confirmed by official readback, zero pending. No credential/device migration.
- `[x]` Publish immutable 0.2.20 service and 0.1.0 signer assets with matching Java source, finish CI and host signed-catalog/HTTPS dependency verification. Retain all previous immutable packages. Remove this task when publication completes.
