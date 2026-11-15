"""Private media scheduling without accounts, network or a decoder installation."""
import os
import threading
import unittest
from unittest.mock import patch
from lazybuddy_hongguo.media import Media


class Account:
    sync_error = None

    class probe:
        state = 'signed_in'
        saved = True

    def pending_progress(self):
        return True

    def call(self, request):
        raise OSError('fixture save failure')


class Tests(unittest.TestCase):
    def test_closed_media_reports_its_final_progress_transaction_until_it_finishes(self):
        media=Media(Account());entered=threading.Event();release=threading.Event()
        def sync(request):entered.set();release.wait(2);return {}
        with patch.object(media.account,'call',side_effect=sync):
            try:
                reply=media.call('media.close',{})
                self.assertTrue(entered.wait(1));self.assertFalse(reply['loaded']);self.assertTrue(reply['progress_pending'])
            finally:
                worker=media.flush_thread;release.set()
                if worker:worker.join(2)
            self.assertFalse(media.state()['progress_pending'])

    def test_failed_spawn_releases_job_and_clears_loading(self):
        media = Media(Account())
        with patch.dict(os.environ, LAZYBUDDY_INSTANCE='qa-media', LAZYBUDDY_PLAYER_REAL='1'), \
                patch('lazybuddy_hongguo.media.Job') as job:
            job.return_value.spawn.side_effect = OSError('fixture spawn failure')
            with self.assertRaises(OSError):
                media.open(dict(series='123', episode=1, pipe=r'\\.\pipe\lazybuddy-media-0123456789abcdef'))
            self.assertFalse(media.loading)
            self.assertIsNone(media.input_job)
            job.return_value.stop.assert_called_once()
            job.return_value.close.assert_called_once()

    def test_failed_flush_releases_worker_for_next_explicit_attempt(self):
        media = Media(Account())
        worker = media.flush()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(media.flush_thread)
        self.assertEqual(media.local_error, 'progress_sync_failed')
        second = media.flush()
        second.join(2)
        self.assertIsNot(worker, second)

    def test_old_input_failure_cannot_close_current_activation(self):
        media = Media(Account())
        media.generation = 2
        media.loading = True
        media.events.put((1, dict(ok=False, error='media_input_failed')))
        media.pump()
        self.assertTrue(media.loading)
        self.assertIsNone(media.error)


if __name__ == '__main__':
    unittest.main()

class DiagnosticRelay(unittest.TestCase):
    def test_async_input_failure_survives_in_api_state(self):
        from types import SimpleNamespace
        from lazybuddy_hongguo.media import Media
        media=Media(SimpleNamespace(sync_error=None));media.browser=True;media.loading=True
        detail={'stage':'playback','http_status':200,'body_bytes':0,'body_read_ok':True}
        media.events.put((media.generation,{'ok':False,'error':'app_playback_empty_response','diagnostic':detail}))
        media.pump();state=media.state()
        self.assertEqual(state['diagnostic'],detail);self.assertEqual(state['error'],'app_playback_empty_response');self.assertFalse(state['loading'])
        media.close(wait=False)
