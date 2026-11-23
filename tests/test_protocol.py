import unittest
import threading
import base64
from lazybuddy_hongguo.protocol import Service


class Backend:
    write_pending=False
    def quiesce(self):pass
    def call(self, request):
        return dict(state='signed_in', name='fixture', qr=[], favorites=[dict(id='1', title='fixture',
            cover='SECRET_SIGNED_URL', cookies='SECRET_COOKIE')], owner='SECRET_UID',
            playback_session=dict(profile='SECRET_DEVICE', cookies='SECRET_COOKIE'))


class ProtocolTests(unittest.TestCase):
    def test_deferred_search_releases_control_and_discarded_covers_stay_private(self):
        entered=threading.Event();release=threading.Event()
        def search(request,cancelled):
            entered.set();release.wait(2)
            return dict(ok=True,data=dict(items=[dict(id='1',_cover='private')]))
        service=Service(Backend,search)
        def call(operation,**args):return service.handle(dict(version=1,id='fixture',method=operation,args=args))
        job=call('work.begin',method='search',args={'query':'test'})['data']['job']
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(call('work.status',job=job)['data']['pending'])
            self.assertTrue(call('lifecycle.suspend')['ok'])
            self.assertEqual(call('work.status',job=job)['error']['code'],'work_cancelled')
        finally:
            release.set()
            for work in service.work.values():work.thread.join(2)
        self.assertFalse(service.covers)

    def test_close_has_one_budget_for_in_flight_account_writes(self):
        release=threading.Event()
        service=Service(Backend);service.account=Backend();service.account.write_pending=True
        service.account.probe=type('Probe',(),{'cancel':lambda self:None})()
        worker=threading.Thread(target=release.wait,daemon=True)
        worker.start();service.operation=(worker,None,'favorites.set')
        try:
            service.close(timeout=.01)
            self.assertTrue(worker.is_alive())
            self.assertIsNone(service.account)
        finally:release.set();worker.join(2)
    def test_cloud_progress_is_async_and_local_snapshot_remains_available(self):
        entered=threading.Event();release=threading.Event()
        class Account(Backend):
            def call(self,request):
                if request['command']=='sync':entered.set();release.wait(2)
                return dict(super().call(request),history={'123':dict(episode=1,time=12.,updated=100.)})
        service=Service(Account)
        def call(method):return service.handle(dict(version=1,id='fixture',method=method))
        call('account.restore')
        try:
            self.assertEqual(call('progress.sync')['data']['operation'],'pending')
            self.assertTrue(entered.wait(1))
            self.assertEqual(call('progress.read')['data']['history']['123']['time'],12.)
        finally:
            release.set()
            if service.operation:service.operation[0].join(2)
        result=call('account.status')['data']
        self.assertEqual(result['operation_method'],'progress.sync');self.assertIsNone(result['operation'])
    def test_qr_is_a_compact_png_payload_instead_of_a_json_integer_array(self):
        class Account:
            def call(self,request):return dict(state='pending',qr=b'fixture-png')
        reply=Service(Account).handle(dict(version=1,id='fixture',method='account.status'))
        self.assertEqual(base64.b64decode(reply['data']['qr_png']),b'fixture-png')
        self.assertNotIn('qr',reply['data'])
    def test_close_stops_media_before_waiting_for_an_account_write(self):
        entered=threading.Event();release=threading.Event();stopped=threading.Event()
        class Account(Backend):
            class probe:
                @staticmethod
                def cancel():pass
            def call(self,request):
                if request['command']=='favorite_set':
                    self.write_pending=True;entered.set();release.wait(2);self.write_pending=False
                return super().call(request)
        class Media:
            def __init__(self,account):pass
            def call(self,method,args):return dict(playing=False)
            def close(self,wait=True):stopped.set()
        service=Service(Account,media_factory=Media)
        for method,args in [('account.restore',{}),('media.status',{}),('favorites.set',dict(series='1',favorite=True))]:service.handle(dict(version=1,id='fixture',method=method,args=args))
        self.assertTrue(entered.wait(1))
        closing=threading.Thread(target=service.close);closing.start()
        try:self.assertTrue(stopped.wait(.5));self.assertTrue(closing.is_alive())
        finally:release.set();closing.join(2)
        self.assertFalse(closing.is_alive())
    def test_slow_favorite_write_does_not_block_pause_and_requires_completion_poll(self):
        entered=threading.Event();release=threading.Event()
        class Account(Backend):
            def call(self,request):
                if request['command']=='favorite_set':entered.set();release.wait(2)
                return super().call(request)
        class Media:
            def __init__(self,account):pass
            def call(self,method,args):return dict(playing=False)
        service=Service(Account,media_factory=Media)
        def call(method,**args):return service.handle(dict(version=1,id='fixture',method=method,args=args))
        call('account.restore')
        try:
            pending=call('favorites.set',series='1',favorite=True)
            self.assertEqual(pending['data']['operation'],'pending')
            self.assertTrue(entered.wait(1))
            self.assertFalse(call('media.pause')['data']['playing'])
            self.assertEqual(call('account.status')['data']['operation'],'pending')
            self.assertEqual(call('account.logout')['error']['code'],'account_busy')
        finally:
            release.set()
            if service.operation:service.operation[0].join(2)
        completed=call('account.status')
        self.assertIsNone(completed['data']['operation'])
        self.assertIsNone(service.operation)
    def test_public_reply_excludes_private_session_and_media_fields(self):
        service = Service(Backend)
        reply = service.handle(dict(version=1, id='one', method='account.status'))
        self.assertTrue(reply['ok'])
        self.assertNotIn('SECRET', str(reply))
        self.assertEqual(reply['data']['favorites'][0]['id'], '1')

    def test_health_and_invalid_requests_do_not_create_backend(self):
        def forbidden():
            self.fail('backend must not be started')
        service = Service(forbidden)
        self.assertTrue(service.handle(dict(version=1, id='one', method='health'))['ok'])
        for request in [None, dict(version=1,id='bad',method={}),dict(version=1,id='bad',method=[]), dict(version=2, id='one', method='account.login'),
                        dict(version=1, id='one', method='arbitrary'),
                        dict(version=1, id='one', method='favorites.set', args=dict(series='../', favorite=True))]:
            self.assertFalse(service.handle(request)['ok'])

    def test_favorite_cover_survives_service_restart(self):
        import os,tempfile
        from unittest.mock import patch
        from lazybuddy_hongguo import covers
        class Account(Backend):
            def call(self,request):
                return dict(state='signed_in',favorites=[dict(id='123',title='fixture',cover='https://one.byteimg.com/image?signature=SECRET')])
        request=dict(version=1,id='fixture',method='cover.read',args=dict(series='123'))
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=directory),patch.object(covers,'_download',return_value=dict(width=1,height=1,rgba='/wAA/w==')) as download:
            first=Service(Account)
            first.handle(dict(version=1,id='restore',method='account.restore'))
            before=first.handle(request)
            self.assertTrue(before['ok'])
            restarted=Service(Account)
            after=restarted.handle(request)
            self.assertTrue(after['ok']);self.assertEqual(after['data'],before['data'])
            self.assertEqual(download.call_count,1)
            self.assertNotIn('SECRET',str(after))
            request['args']['series']='456'
            self.assertEqual(restarted.handle(request)['error']['code'],'cover_unavailable')
            self.assertEqual(download.call_count,1)

    def test_search_projects_private_covers_before_reply(self):
        service=Service(Backend,lambda request:dict(version=1,id=request['id'],ok=True,data=dict(items=[dict(id='1',title='fixture',_cover='SECRET_URL')],page=1,has_more=False)))
        reply=service.handle(dict(version=1,id='search',method='search',args=dict(query='fixture')))
        self.assertTrue(reply['ok'])
        self.assertNotIn('SECRET',str(reply))
        self.assertEqual(service.covers['1'],'SECRET_URL')

    def test_media_allowlist_and_progress_busy_boundary(self):
        class Media:
            def __init__(self,account):pass
            def call(self,method,args):return dict(playing=True)
        service=Service(Backend,media_factory=Media)
        self.assertFalse(service.handle(dict(version=True,id='bad',method='health'))['ok'])
        self.assertFalse(service.handle(dict(version=1,id='bad',method='media.open',args=dict(url='SECRET')))['ok'])
        self.assertTrue(service.handle(dict(version=1,id='play',method='media.status'))['ok'])
        reply=service.handle(dict(version=1,id='sync',method='progress.sync'))
        self.assertEqual(reply['error']['code'],'player_busy')


if __name__ == '__main__':
    unittest.main()
