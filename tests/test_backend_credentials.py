import sys
from pathlib import Path
"""Credential boundaries; all Windows storage calls are mocked."""
import unittest
from unittest.mock import patch
from lazybuddy_hongguo.backend import credentials as c


PROFILE = dict(cdid='fixture', openudid='fixture', clientudid='fixture', oaid_id='fixture',
               req_id='fixture', device_id_str='123', install_id_str='456', ttreq='fixture',
               created_at='2026-11-13T00:00:00Z')


class Tests(unittest.TestCase):
    def test_preview_namespace_is_explicit_and_separates_credentials(self):
        self.assertEqual(c.prefix(''),'LazyBuddy/Hongguo')
        self.assertNotEqual(c.prefix('shell-preview'),c.prefix(''))
        for scope in ('../website','A','x\n','x'*49):
            with self.assertRaises(ValueError):c.prefix(scope)
    def test_scoped_preview_writes_only_its_own_device_cache(self):
        with patch.object(c,'PREFIX',c.prefix('shell-preview')),patch.dict(c.os.environ,LAZYBUDDY_INSTANCE='shell-preview'),patch.object(c,'_read',return_value=None),patch.object(c,'_write') as write:
            self.assertTrue(c.remember_device('123',PROFILE))
            self.assertTrue(write.call_args.args[0].startswith(c.prefix('shell-preview')+'/device/'))
    def setUp(self):
        saved = patch.object(c, 'read', return_value=dict(v=1, uid='123', cookies={'sessionid':'fixture'}))
        saved.start();self.addCleanup(saved.stop)

    def test_device_is_separate_and_account_bound(self):
        self.assertNotEqual(c.device_target('123'), c.TARGET)
        self.assertNotEqual(c.device_target('123'), c.device_target('456'))
        self.assertNotIn('/123', c.device_target('123'))
        with patch.object(c, '_read', return_value=dict(v=1, uid='123', profile=PROFILE)):
            self.assertEqual(c.read_device('123'), PROFILE)
            with self.assertRaises(ValueError):c.read_device('456')

    def test_profile_rejects_secrets_urls_and_unknown_fields(self):
        for key in ('url', 'key', 'cookies', 'token'):
            with self.assertRaises(ValueError):c.validate_device(PROFILE | {key: 'secret'})
        for key, value in [('device_id_str', '0'), ('ttreq', 'x\n'), ('device', {'url': 'private'})]:
            with self.assertRaises(ValueError):c.validate_device(PROFILE | {key: value})

    def test_default_caches_without_overwriting_website(self):
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, '_read', return_value=None), patch.object(c, '_write') as write:
            self.assertTrue(c.remember_device('123', PROFILE))
            self.assertEqual(write.call_args.args[0], c.device_target('123'))
            self.assertEqual(write.call_args.args[1], dict(v=1, uid='123', profile=PROFILE))

    def test_existing_device_is_not_rotated_or_corrupt_record_overwritten(self):
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, '_read', return_value=dict(v=1, uid='123', profile=PROFILE)), patch.object(c, '_write') as write:
            self.assertTrue(c.remember_device('123', PROFILE))
            self.assertFalse(c.remember_device('123', PROFILE | {'device_id_str': '789'}))
            write.assert_not_called()
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, '_read', return_value={}), patch.object(c, '_write') as write:
            with self.assertRaises(ValueError):c.remember_device('123', PROFILE)
            write.assert_not_called()

    def test_qa_never_writes_or_opens_device_store(self):
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='qa-cache'), patch.object(c, '_read') as read, patch.object(c, '_write') as write:
            self.assertFalse(c.remember_device('123', PROFILE))
            read.assert_not_called();write.assert_not_called()

    def test_late_result_does_not_recreate_logged_out_device(self):
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, 'read', return_value=None), patch.object(c, '_write') as write:
            self.assertFalse(c.remember_device('123', PROFILE));write.assert_not_called()

    def test_same_device_ticket_can_refresh_without_changing_identity(self):
        with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, '_read', return_value=dict(v=1, uid='123', profile=PROFILE)), patch.object(c, '_write') as write:
            updated=PROFILE | {'ttreq':'refreshed-fixture'}
            self.assertTrue(c.remember_device('123', updated))
            self.assertEqual(write.call_args.args[1]['profile'], updated)

    def test_failed_optional_write_preserves_live_playback(self):
        for error in (OSError('fixture'), ValueError('credential_too_large')):
            with patch.dict(c.os.environ, LAZYBUDDY_INSTANCE='default'), patch.object(c, '_read', return_value=None), patch.object(c, '_write', side_effect=error):
                self.assertFalse(c.remember_device('123', PROFILE))

    def test_logout_deletes_only_current_account_device_and_website(self):
        with patch.object(c, 'read', return_value={'uid':'123'}), patch.object(c, '_delete') as delete:
            c.delete()
            self.assertEqual([v.args[0] for v in delete.call_args_list], [c.device_target('123'), c.TARGET])

    def test_existing_website_save_guard_remains(self):
        record=dict(v=1, uid='123', cookies={'sessionid':'fixture'})
        with patch.object(c, 'read', return_value=record), patch.object(c, '_write') as write:
            c.save(record)
            self.assertEqual(write.call_args.args[0], c.TARGET)
            with self.assertRaises(ValueError):c.save(record | {'uid':'456'})
            self.assertEqual(write.call_count, 1)

    def test_media_uses_only_same_account_memory_or_saved_device(self):
        import json
        from unittest.mock import Mock
        from lazybuddy_hongguo.backend import app_input as media
        cached=PROFILE | {'device_id_str':'789'}
        passport=Mock();passport.restore.return_value.confirm.return_value='123'
        failure=Mock(returncode=1, stdout=b'{"ok":false,"error":"app_playback_unavailable"}')
        with patch.object(c, 'read_device', return_value=cached), patch.object(c, 'remember_device'), patch.object(media.pathlib.Path, 'is_file', return_value=True), patch.object(media.subprocess, 'run', return_value=failure) as run:
            for owner, expected in [('123', PROFILE), ('456', cached)]:
                with self.assertRaisesRegex(ValueError, 'app_playback_unavailable'):
                    media.resolve('12345', 222, '720p', dict(owner=owner, profile=PROFILE), passport)
                self.assertEqual(json.loads(run.call_args.kwargs['input'])['profile'], expected)

    def test_empty_player_response_is_distinct_from_access_denial(self):
        import json
        from unittest.mock import Mock
        from lazybuddy_hongguo.backend import app_input as media
        from lazybuddy_hongguo.errors import code
        passport=Mock();passport.restore.return_value.confirm.return_value='123'
        for error,diagnostic,expected in [
            ('app_playback_unavailable',dict(stage='playback',http_status=200,body_bytes=0),'app_playback_empty_response'),
            ('app_playback_unavailable',dict(stage='playback',http_status=200,body_bytes=20),'app_playback_unavailable'),
            ('app_playback_unavailable',dict(stage='playback',http_status=200,body_bytes=0,body_read_ok=False),'app_source_network_error'),
            ('app_access_denied',dict(stage='playback',http_status=403,body_bytes=0),'app_access_denied'),
        ]:
            reply=Mock(returncode=1,stdout=json.dumps(dict(ok=False,error=error,diagnostic=diagnostic)).encode())
            with patch.object(c,'read_device',return_value=PROFILE),patch.object(c,'remember_device'),patch.object(media.pathlib.Path,'is_file',return_value=True),patch.object(media.subprocess,'run',return_value=reply) as run:
                with self.assertRaises(ValueError) as raised:media.resolve('12345',1,'720p',{},passport)
                self.assertEqual(code(raised.exception),expected)
                self.assertEqual(run.call_count,1)

    def test_media_and_identity_overlap_without_skipping_final_identity_check(self):
        import json, threading
        from unittest.mock import Mock
        from lazybuddy_hongguo.backend import app_input as media
        for verified in (True, False):
            verifying=threading.Event();reading=threading.Event();calls=[]
            def confirm(_):
                calls.append(1)
                if len(calls)==1:return '123'
                verifying.set()
                self.assertTrue(reading.wait(2))
                return '123' if verified else '456'
            def source(*_):
                self.assertTrue(verifying.wait(2));reading.set()
                return Mock(total=100)
            passport=Mock();passport.restore.return_value.confirm.side_effect=confirm
            reply=dict(ok=True, key='', url='https://fixture.qznovelvod.com/a', width=1280, height=720,
                       profile=PROFILE, catalog=[dict(number=222, playable=True)])
            with patch.object(c, 'read_device', return_value=PROFILE), patch.object(c, 'remember_device'), patch.object(media.pathlib.Path, 'is_file', return_value=True), patch.object(media.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps(reply).encode())), patch.object(media, 'Source', side_effect=source), patch.object(media, 'Server') as server:
                if verified:
                    result,_=media.resolve('12345', 222, '1080p', {}, passport)
                    self.assertEqual((result['width'],result['height']),(1280,720))
                    self.assertEqual(result['requested_quality'],'1080p')
                    server.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, 'saved_session_verification_failed'):
                        media.resolve('12345', 222, '720p', {}, passport)
                    server.assert_not_called()
                self.assertEqual(len(calls),2)


if __name__ == '__main__':unittest.main()
