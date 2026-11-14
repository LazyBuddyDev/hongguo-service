# Local HEIC cover decoder

Pinned private dependencies: pillow-heif 1.8.1 (BSD-3-Clause), Pillow 12.2.0 (MIT-CMU).
Sources: https://github.com/bigcat88/pillow_heif and https://github.com/python-pillow/Pillow.

Binary wheels and their bundled codec licenses are retained in the private target/native-player-sdk/cover-python installation. Preserve pillow_heif-1.8.1.dist-info/licenses/LICENSE.txt and LICENSES_bundled.txt, and Pillow's license directory, if packaging these runtimes later; bundled libheif and other codec notices have their own terms. Windows release packaging retains the private dependency license directories and these notices.

The helper receives only image bytes via private pipes, never account credentials or URLs, and returns a bounded RGBA thumbnail. It does not process playback media.
