"""Private build inputs belong to this service, separated from build caches."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GO = Path(os.environ.get('LAZYBUDDY_GO_DIR', ROOT / 'target/toolchains/go'))
PYTHON = Path(os.environ.get('LAZYBUDDY_PYTHON_DIR', ROOT / 'target/toolchains/python'))
WHEELS = Path(os.environ.get('LAZYBUDDY_PYTHON_WHEELS_DIR', ROOT / 'target/downloads/python-wheels'))
GSTREAMER_SDK = Path(os.environ.get('LAZYBUDDY_GSTREAMER_SDK_DIR', ROOT / 'target/sdks/gstreamer'))
GSTREAMER = GSTREAMER_SDK / 'PFiles64/gstreamer/1.0/msvc_x86_64'
