import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('selection',Path(__file__).resolve().parents[1]/'scripts/check-changes.py')
selection=importlib.util.module_from_spec(spec);spec.loader.exec_module(selection)

class Selection(unittest.TestCase):
    def test_browser_resource_change_does_not_select_account_or_full_suite(self):
        self.assertEqual(selection.select(['src/lazybuddy_hongguo/backend/progressive.py']),['test_backend_progressive','test_browser_playback'])
        self.assertEqual(selection.select(['docs/media-runtime.md']),[])
        self.assertEqual(selection.select(['scripts/toolchain_paths.py']),['test_toolchain_paths'])

    def test_backend_modules_select_the_tests_for_their_consumers(self):
        for source, tests in {
            'account': {'test_account','test_signer'},
            'passport': {'test_backend_probe'},
            'lease': {'test_account', 'test_cover_cache'},
            'media_container': {'test_backend_media', 'test_backend_progressive'},
        }.items():
            with self.subTest(source=source):
                self.assertEqual(set(selection.select([f'src/lazybuddy_hongguo/backend/{source}.py'])), tests)

if __name__=='__main__':unittest.main()
