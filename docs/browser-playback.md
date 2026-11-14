# Browser playback resources

The 0.2.0 candidate exposes compressed MP4 resources instead of requiring a native decoder. The service retains identity checks, episode permissions, quality selection and bounded offset-preserving Range preparation. The browser performs demuxing, decoding, AV synchronization and rendering. `media-runtime` is absent from the feature's required dependencies and default package build; Python and the bundled Go/search helpers remain required. Existing signed 0.1.0 catalog entries are unchanged. Do not deliver this candidate to the old Iced media consumer before its host migration.

The control transport remains version-1 JSON Lines on the private child pipes:

| Method | Arguments | Result |
| --- | --- | --- |
| `playback.open` | `series` string, `episode` integer, optional `quality`, explicit `origin` such as `http://tauri.localhost` | Starts preparation; returns a session generation and loading state |
| `playback.status` | none | Current prepared/loading/error state; episode list, qualities, source dimensions and resource when ready |
| `playback.suspend` / `playback.resume` | `session` integer | Stops/allows resource reads; loading preparation is cancelled on suspend |
| `playback.checkpoint` | `session`, decoded `position` and `duration` seconds, optional boolean `final` | Saves the same account-bound progress transaction; final requests a flush |
| `playback.close` | `session` | Releases the input process and resource, and finalizes existing progress work |

Ready responses contain `prepared: true`, `resource: {url, mime: "video/mp4"}`, `session`, `suspended` and sanitized error/progress fields. A resource URL identifies a random capability on 127.0.0.1; it is not the upstream signed URL. Do not persist or log it. The browser must use CORS mode, for example `<video crossorigin="anonymous">`. Each resource permits only the origin supplied to open and its exact Host/path. GET, HEAD, single Range and OPTIONS are supported. Private service-only POST controls suspend/resume; requests with browser Origin/Sec-Fetch headers cannot use that control. No arbitrary URL fetching endpoint is exposed.

An accepted open is not proof that a browser decoded a frame. Loading status is polled only while the content page is active. Browser `loadedmetadata`, actual dimensions, frame callback `mediaTime`, errors and EOS own playback feedback. Do not derive presented media time from the native IPC clock or from a requested seek target. Unsupported codecs are errors; no automatic CPU transcoding is introduced.

On hide, pause and unload the browser source, then suspend the resource. A late upstream read is bounded by the existing timeout; it must not populate the cancelled generation's cache or trigger subsequent reads. Resume the same resource and position while paused. On page/settings departure or exit, close the session/process tree. Controls/checkpoints require the matching session generation. The browser must report true watched frames rather than slider previews; the prototype's real-account progress wiring remains pending.

Validation on 2026-11-14: focused browser/Range/input/media/protocol/selection modules pass (37 tests). An external, explicitly staged synthetic fixture package with only Python dependency drives the real WebView: H.264 and H.265/AAC decode, paused seek presents mediaTime 3.1s, hide unloads src and server rejects reads, resume restores 3.1s without playing, settings invalidate the old resource, normal exit completes. No GStreamer decoder is spawned. AAC is muted; real red-fruit permissions, processed real streams, audio quality and programme AV sync are not established by this fixture.

The fixture belongs to this repository and is never shipped as a release entry. Stage it with `python -B scripts/verify/stage-browser-fixture.py --output target/packages-browser-fixture`. Point the external host at that package directory and set `LAZYBUDDY_BROWSER_FIXTURE_FILE` to an explicitly generated short synthetic MP4. The production service entry remains `main.py`; no account/URL fixture override is added there.
