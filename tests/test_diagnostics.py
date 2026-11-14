import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from lazybuddy_hongguo import diagnostics as d

class Tests(unittest.TestCase):
    def test_original_exception_location_is_logged_without_its_message(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=root):
            try:raise ValueError('SECRET_SIGNED_URL')
            except ValueError as error:self.assertTrue(d.record('media_request_failed',stage='prepare',exception=error))
            text=(Path(root)/'logs/media.log').read_text(encoding='utf-8');row=json.loads(text)
            self.assertEqual(row['exception_type'],'ValueError');self.assertEqual(row['stack'][-1]['file'],'test_diagnostics.py')
            self.assertNotIn('SECRET',text)
    def test_redirect_context_is_useful_without_secrets_or_full_urls(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=root):
            self.assertTrue(d.record('media_redirect_target_rejected',stage='redirect',context=dict(series='123',episode=2,quality='720p',cookies='SECRET_COOKIE'),status=302,hop=1,source='https://user:SECRET_PASSWORD@one.qznovelvod.com/SECRET_PATH?token=SECRET_TOKEN',target='https://other.invalid/private?key=SECRET_KEY',mode='direct'))
            text=(Path(root)/'logs/media.log').read_text(encoding='utf-8');row=json.loads(text)
            self.assertEqual(row['source_host'],'one.qznovelvod.com');self.assertEqual(row['target_host'],'other.invalid')
            self.assertEqual(row['series'],'123');self.assertEqual(row['http_status'],302)
            self.assertTrue(row['stack']);self.assertIsInstance(row['stack'][-1]['line'],int)
            self.assertNotIn('SECRET',text);self.assertNotIn('https://',text)
    def test_rotation_is_bounded_and_write_failures_do_not_break_playback(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=root),patch.object(d,'MAX_BYTES',1024):
            for _ in range(20):self.assertTrue(d.record('media_redirect_limit',stage='redirect',hop=6))
            logs=list((Path(root)/'logs').glob('media.log*'));self.assertEqual(len(logs),3)
            self.assertLessEqual(sum(p.stat().st_size for p in logs),3*1024)
            with patch.object(d.Path,'mkdir',side_effect=OSError('fixture')):self.assertFalse(d.record('media_network_error',stage='range'))
