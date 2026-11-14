`hongguo_media.wrapped_key` is a Python adaptation of
beilunyang/openhongguo `internal/drm/spade.go`, revision
015a388112ee148a7d2dfb7ecfafe171bbab957f (Apache-2.0).

Source: https://github.com/beilunyang/openhongguo/blob/015a388112ee148a7d2dfb7ecfafe171bbab957f/internal/drm/spade.go

Modified for BriefDock: accept only website version 22, with its positive rolling
offset, not the App spade permutation; bounded AES-128 material validation; no anonymous device,
signing, network or file APIs are imported into that Python adaptation. The MP4 parser,
memory HTTP service and player integration are BriefDock implementation.
The source project's README describes personal study/research use and disallows
non-research commercial use; the website adaptation is retained as a compatibility input.
The App route is now the local default Windows player; no installer has been published with it.

The App resolver separately uses the non-test Go SDK sources plus sdk/briefdock_account.go
at that same revision, retained under vendor/openhongguo with its LICENSE.
Its custom BriefDock transport permits only the two official video reads, the explicit video-shelf read/update, fixed watch-progress read/upload, and
device registration. Automatic device resets and retries are disabled; device
profiles and saved account cookies are passed in private process pipes and
kept out of configuration files and public reports. The native App route is
not yet included in a published installer.

BriefDock also independently adds fixed GET read_progress/list/v1/ and POST
read_progress/upload/v1/ account checkpoint operations. The transport permits only
these exact method/path pairs, no history/favorite deletion or arbitrary endpoint.
Protocol field reference (not copied implementation):
https://github.com/tsukiyo-zero/hongguoTV/blob/77a99f509b8a5c586bf6ef453147cf1003203970/kotlin-tv/core/src/main/kotlin/com/hongguotv/core/CloudAccount.kt
Playback records are timestamp-merged and uploads are read back before confirmation;
background test instances require a separate explicit progress-write flag.

The fixed POST /reading/bookapi/bookshelf/video/update/v1/ independently implements
single-series add/cancel wire fields from the same pinned protocol reference above.
No collection replacement, bulk cancellation, arbitrary URL or automatic write retry
is accepted. Favorite state is read before the operation and read back afterward;
isolated writes additionally require BRIEFDOCK_FAVORITES_REAL=1.
