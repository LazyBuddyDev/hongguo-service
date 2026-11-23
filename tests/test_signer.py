import io
import os
import json
import queue
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from lazybuddy_hongguo.signer import LocalSigner


class Tests(unittest.TestCase):
    def test_media_handoff_is_private_and_keeps_generation(self):
        signer=LocalSigner();process=Mock();process.poll.return_value=None
        process.stdin=io.BytesIO();events=queue.Queue()
        with patch.object(signer,'environment',return_value={'LAZYBUDDY_HONGGUO_SIGNER_URL':'http://127.0.0.1:1234','LAZYBUDDY_HONGGUO_SIGNER_TOKEN':'fixture'}):
            signer.prepare_input(process,b'{"series":"123"}',events,7).join(2)
            request=json.loads(process.stdin.getvalue())
            self.assertEqual(request['series'],'123')
            self.assertEqual(request['_signer']['LAZYBUDDY_HONGGUO_SIGNER_TOKEN'],'fixture')
            self.assertTrue(events.empty())
        with patch.object(signer,'environment',side_effect=ValueError('SECRET')):
            signer.prepare_input(process,b'{}',events,8).join(2)
            self.assertEqual(events.get_nowait(),(8,dict(ok=False,error='app_source_unavailable')))

    def test_legacy_and_explicit_remote_do_not_start_java(self):
        signer=LocalSigner()
        with patch.dict(os.environ,{},clear=True),patch('lazybuddy_hongguo.signer.Job') as job:
            self.assertNotIn('LAZYBUDDY_HONGGUO_SIGNER_URL',signer.environment())
            os.environ['LAZYBUDDY_HONGGUO_SIGNER_URL']='https://signer.example'
            self.assertEqual(signer.environment()['LAZYBUDDY_HONGGUO_SIGNER_URL'],'https://signer.example')
            job.assert_not_called()

    def test_local_is_private_reused_and_closed(self):
        signer=LocalSigner()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'java/bin').mkdir(parents=True)
            (root/'java/bin/java.exe').touch()
            (root/'lib').mkdir()
            process=Mock();process.poll.return_value=None
            job=Mock();job.spawn.return_value=process
            opener=Mock();opener.open.side_effect=lambda *a,**k:io.BytesIO(b'{"service":"openhongguo-signer","ready":true}')
            with patch.dict(os.environ,{'LAZYBUDDY_DEPENDENCY_HONGGUO_SIGNER_DIR':directory,'JAVA_TOOL_OPTIONS':'ambient'},clear=True),patch('lazybuddy_hongguo.signer.Job',return_value=job),patch('urllib.request.build_opener',return_value=opener):
                first=signer.environment();second=signer.environment()
                self.assertEqual(first,second)
                self.assertTrue(first['LAZYBUDDY_HONGGUO_SIGNER_URL'].startswith('http://127.0.0.1:'))
                self.assertNotIn('LAZYBUDDY_HONGGUO_SIGNER_TOKEN',os.environ)
                arguments=job.spawn.call_args
                self.assertEqual(arguments.kwargs['env']['SIGNER_HOST'],'127.0.0.1')
                self.assertEqual(arguments.kwargs['env']['SIGNER_TOKEN'],first['LAZYBUDDY_HONGGUO_SIGNER_TOKEN'])
                self.assertNotIn('JAVA_TOOL_OPTIONS',arguments.kwargs['env'])
                job.spawn.assert_called_once()
                signer.close()
                job.stop.assert_called_once();job.close.assert_called_once();process.wait.assert_called_once()

    def test_failed_start_is_reaped_without_legacy_fallback(self):
        signer=LocalSigner()
        with patch('pathlib.Path.is_file',return_value=True),patch('pathlib.Path.is_dir',return_value=True),patch('lazybuddy_hongguo.signer.Job') as job:
            job.return_value.spawn.return_value.poll.return_value=1
            with patch.dict(os.environ,{'LAZYBUDDY_DEPENDENCY_HONGGUO_SIGNER_DIR':'fixture'},clear=True):
                with self.assertRaisesRegex(ValueError,'app_signer_unavailable'):signer.environment()
            job.return_value.stop.assert_called_once()
            self.assertIsNone(signer.process)
