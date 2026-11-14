# LazyBuddy Hongguo Service

Independent Windows x64 account/media API, owned by LazyBuddyDev/hongguo-service. The repository owns account, search, official favorites, progress, covers, media input, the optional decoder worker, manifests, packaging and related tests. It does not import the desktop source or Iced. Any client can call JSON-lines API v1.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/python.exe -B scripts/check-changes.py --base origin/main
```

For source runs set PYTHONPATH=src and run `python -m lazybuddy_hongguo`; health does not load an account or decoder. See docs/module-api.md for business fields and [browser playback](docs/browser-playback.md) for the resource-session API, connection routing and diagnostics in source version 0.2.5. The user approved integrating this code into main; this does not publish a software release or update the signed module catalog. The browser handles decoding/rendering; the service retains account, permission and bounded media preparation.

Build feature/runtime packages independently:

```powershell
cargo build --release --locked --manifest-path search/Cargo.toml
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-hongguo-resolver.ps1
python -B scripts/prepare-module-runtimes.py
python -B scripts/package-modules.py --output target/packages
```

SDKs default to target/native-player-sdk. LAZYBUDDY_SDK_DIR may explicitly select an existing verified private SDK cache; this is a build input, never a desktop source dependency. Go output is target/hongguo-app-resolver.exe, Rust search output is search/target/release, and Python dependencies stay private. Default packaging emits hongguo and python-runtime ZIPs; the browser feature does not require GStreamer. The older native decoder remains an explicit `--modules media-runtime` build, requiring prepare-media-sdk.ps1. No SDK headers, account data, signed media URLs or developer environment are bundled. The candidate catalog is not published to the old Iced host.

Credentials use Windows secure storage in the LazyBuddy namespace. Account restoration, App playback permission, official favorite writes and cloud progress confirmation require separate validation. Identity is not proof of every episode's permission. QR PNG is Base64; only identity verification plus secure saving completes login. Cancel and logout differ. Official account transactions run asynchronously and cannot block media control; local progress survives failed or canceled synchronization.

Isolated instances require separate explicit permissions for real playback, favorite writes and progress uploads. Unit tests use fixtures, never real credentials or upstream writes. Synthetic JPEG/H.264/H.265/AAC checks are not proof of real account permissions or program AV synchronization.

Optional integration scripts under scripts/verify accept LAZYBUDDY_HOST_DIR pointing to built host/CLI/probe executables, LAZYBUDDY_PACKAGES_DIR for staged feature/runtime packages, and LAZYBUDDY_SDK_DIR for local fixture generation. They call the external host through API and import only this repository's service source. Physical foreground input and real-account tests are not part of the normal CI run.

Own code is MIT, copyright 2026 Leager; third-party notices live in vendor/openhongguo and licenses. Binary redistribution and signed catalog publication have separate verification gates. The manual packaging workflow requires the root LICENSE.
