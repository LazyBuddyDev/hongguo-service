import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('LAZYBUDDY_GO_DIR', 'LAZYBUDDY_PYTHON_DIR', 'LAZYBUDDY_PYTHON_WHEELS_DIR', 'LAZYBUDDY_GSTREAMER_SDK_DIR')

def load():
    spec = importlib.util.spec_from_file_location('toolchain_paths', ROOT / 'scripts/toolchain_paths.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class ToolchainPaths(unittest.TestCase):
    def test_defaults_are_owned_by_service_and_separate_tools_from_downloads(self):
        with patch.dict(os.environ, {key: value for key, value in os.environ.items() if key not in KEYS}, clear=True):
            paths = load()
        self.assertEqual(paths.GO.parent, ROOT / 'target/toolchains')
        self.assertEqual(paths.PYTHON.parent, paths.GO.parent)
        self.assertEqual(paths.WHEELS.parent, ROOT / 'target/downloads')
        self.assertEqual(paths.GSTREAMER_SDK.parent, ROOT / 'target/sdks')
        self.assertTrue(paths.GSTREAMER.is_relative_to(paths.GSTREAMER_SDK))

    def test_overriding_python_does_not_redirect_go_or_native_sdk(self):
        override = str(ROOT / 'tmp/custom-python')
        with patch.dict(os.environ, {key: value for key, value in os.environ.items() if key not in KEYS}, clear=True):
            defaults = load()
            with patch.dict(os.environ, {'LAZYBUDDY_PYTHON_DIR': override}):
                paths = load()
        self.assertEqual(paths.PYTHON, Path(override))
        self.assertEqual(paths.GO, defaults.GO)
        self.assertEqual(paths.GSTREAMER, defaults.GSTREAMER)

if __name__ == '__main__':
    unittest.main()
