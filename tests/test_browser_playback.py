"""Browser resource access and lifecycle, using memory data and localhost only."""
import http.client
import json
import threading
import unittest
from unittest.mock import Mock,patch
from lazybuddy_hongguo.backend.progressive import Server
from lazybuddy_hongguo.media import Media

ORIGIN='http://tauri.localhost'

class Source:
    total=1024
    connection=None
    reads=0
    def read(self,start,end,cancelled):
        if cancelled():return
        self.reads+=1
        yield bytes(index%256 for index in range(start,end+1))


class BrowserPlayback(unittest.TestCase):
    def pair(self):
        account=Mock(sync_error=None);account.probe.state='signed_in';account.probe.saved=True
        account.pending_progress.return_value=False;account.current_identity.return_value=True
        current=Media(account);current.browser=True;current.resource='current';current.arguments=dict(series='123',episode=1,quality='720p',origin=ORIGIN)
        current.metadata=dict(series='123',episode=1,episodes=[1,3,4]);current.resolver=dict(owner='private',catalog=[])
        candidate=Media(account)
        def start(args,**_):
            candidate.arguments=args;candidate.browser=True;candidate.metadata=dict(series='123',episode=3,episodes=[1,3,4]);candidate.loading=True
        return current,candidate,start

    def test_danmaku_uses_current_catalog_item_and_cancels_on_close(self):
        current,_,_=self.pair()
        current.resolver.update(series='123',catalog=[dict(id='111',number=1,playable=True)])
        session=current.generation
        args=dict(session=session)
        started=threading.Event()
        stopped=threading.Event()
        wires=[]
        def run(_args,*,input,cancelled,**_):
            wires.append(json.loads(input))
            started.set()
            if cancelled.wait(3):stopped.set()
            return Mock(returncode=0,stdout=b'{"ok":true,"items":[]}')
        with patch('lazybuddy_hongguo.media.run_helper',side_effect=run) as helper:
            with self.assertRaises(ValueError):current.call('danmaku.read',dict(session=session-1))
            self.assertEqual(current.call('danmaku.read',args),dict(pending=True))
            self.assertTrue(started.wait(3))
            self.assertEqual(current.call('danmaku.read',args),dict(pending=True))
            self.assertEqual(wires,[dict(mode='danmaku',series='123',item='111',profile=None)])
            current.close(wait=False)
            self.assertTrue(stopped.wait(3))
            self.assertIsNone(current.danmaku_work)
            with self.assertRaises(ValueError):current.call('danmaku.read',args)
            helper.assert_called_once()

    def test_prefetch_is_one_verified_adjacent_episode_and_does_not_replace_current(self):
        current,candidate,start=self.pair();generation=current.generation
        with patch('lazybuddy_hongguo.media.Media',return_value=candidate),patch.object(candidate,'open',side_effect=start) as opened:
            current.call('playback.prefetch',dict(session=generation));current.call('playback.prefetch',dict(session=generation))
        self.assertEqual(opened.call_count,1);self.assertEqual(opened.call_args.kwargs,dict(browser=True,warmup=True))
        self.assertEqual(candidate.arguments['episode'],3);self.assertEqual(current.resource,'current');self.assertEqual(current.generation,generation)
        self.assertIsNone(current.recorded);self.assertIsNone(candidate.recorded)
        with self.assertRaises(ValueError):current.call('playback.prefetch',dict(session=generation-1))
        current.cancel_prefetch()

    def test_ready_or_inflight_prefetch_is_adopted_without_second_open(self):
        for ready in (True,False):
            current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN))
            candidate.resolver=current.resolver;candidate.resource='prepared' if ready else None;candidate.loading=not ready;current.next_media=candidate
            session=candidate.generation
            with patch('lazybuddy_hongguo.media.Job',side_effect=AssertionError('must reuse input pipeline')):
                state=current.open(candidate.arguments,browser=True)
            self.assertEqual(state['session'],session);self.assertEqual(state['prepared'],ready);self.assertEqual(state['loading'],not ready)
            self.assertIsNone(current.next_media);self.assertIsNone(current.recorded)

    def test_failed_prefetch_does_not_break_current_or_retry_at_handoff(self):
        current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN));candidate.resolver=current.resolver
        candidate.loading=False;candidate.error='media_access_denied';current.next_media=candidate
        self.assertIsNone(current.state()['error']);self.assertEqual(current.resource,'current')
        with patch('lazybuddy_hongguo.media.Job',side_effect=AssertionError('denied source cannot retry')):
            state=current.open(candidate.arguments,browser=True)
        self.assertEqual(state['error'],'media_access_denied');self.assertFalse(state['loading'])

    def test_cancel_stops_candidate_and_late_events_cannot_repopulate_it(self):
        current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN));current.next_media=candidate
        generation=candidate.generation;job=Mock();candidate.input_job=job
        current.cancel_prefetch();job.close.assert_called_once();self.assertIsNone(current.next_media)
        candidate.events.put((generation,dict(ok=True)));candidate.pump();self.assertIsNone(candidate.resource)
        self.assertEqual(current.resource,'current')

    def test_suspend_cancels_next_but_keeps_current_resource_and_no_resume_prefetch(self):
        current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN));current.next_media=candidate
        current.resource=self.server.address;session=current.generation
        current.call('playback.suspend',dict(session=session));self.assertIsNone(current.next_media);self.assertTrue(current.suspended)
        self.assertEqual(current.resource,self.server.address)
        with patch('lazybuddy_hongguo.media.Media',side_effect=AssertionError('no hidden/resume preparation')):
            current.call('playback.prefetch',dict(session=session));current.call('playback.resume',dict(session=session))
        self.assertIsNone(current.next_media)

    def test_quality_change_discards_candidate_and_final_episode_never_prefetches(self):
        current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN));current.next_media=candidate
        with patch.object(candidate,'close') as closed,patch('lazybuddy_hongguo.media.Job',side_effect=ValueError('fixture stop')):
            with self.assertRaises(ValueError):current.open(dict(series='123',episode=3,quality='1080p',origin=ORIGIN),browser=True)
        closed.assert_called_once();self.assertIsNone(current.next_media)
        current.browser=True;current.resource='current';current.loading=False;current.metadata['episode']=4
        with patch('lazybuddy_hongguo.media.Media',side_effect=AssertionError('last episode has no next')):current.prefetch()

    def test_candidate_cannot_be_adopted_by_another_account(self):
        current,candidate,start=self.pair();start(dict(series='123',episode=3,quality='720p',origin=ORIGIN));candidate.resolver=current.resolver
        current.next_media=candidate;current.account.current_identity.return_value=False
        with self.assertRaisesRegex(ValueError,'saved_session_verification_failed'):current.open(candidate.arguments,browser=True)
        self.assertIsNone(current.next_media)

    def test_browser_error_returns_diagnostics_without_rebuilding_resource(self):
        media=Media(Mock(sync_error=None));media.browser=True;media.resource='fixture';media.metadata={'series':'123','episode':1};media.arguments={'quality':'720p'}
        reply=media.call('playback.report_error',dict(session=media.generation,code=4))
        self.assertEqual(reply['diagnostic']['browser_code'],4)
        self.assertEqual(reply['diagnostic']['event'],'browser_media_error')
        self.assertEqual(media.resource,'fixture')
        diagnostic=media.diagnostic
        with self.assertRaises(ValueError):media.call('playback.report_error',dict(session=media.generation,code=99))
        with self.assertRaises(ValueError):media.call('playback.report_error',dict(session=media.generation-1,code=4))
        self.assertIs(media.diagnostic,diagnostic)
    def test_old_service_session_cannot_close_a_restarted_service(self):
        account=Mock();account.sync_error=None
        with patch('lazybuddy_hongguo.media.secrets.randbelow',side_effect=[101,202]):
            previous=Media(account);current=Media(account)
        current.browser=True;current.resource='fixture'
        with patch.object(current,'close') as close:
            with self.assertRaises(ValueError):current.call('playback.close',dict(session=previous.generation))
            close.assert_not_called()
    def test_unchanged_browser_final_checkpoint_does_not_start_another_sync(self):
        account=Mock();account.sync_error=None
        media=Media(account);media.browser=True;media.resource='fixture';media.recorded=('123',1,3.)
        with patch.object(media,'checkpoint'),patch.object(media,'flush') as flush:
            args=dict(session=media.generation,position=3.,duration=8.,final=True)
            media.call('playback.checkpoint',args);media.call('playback.checkpoint',args);media.close(wait=False)
            flush.assert_called_once()
    def setUp(self):
        self.source=Source();self.server=Server(self.source,origin=ORIGIN)
        self.thread=threading.Thread(target=self.server.serve);self.thread.start()
    def tearDown(self):
        self.server.server.shutdown();self.server.close();self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
    def request(self,method='GET',headers=None,body=None,path=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server.server_port,timeout=2)
        try:
            connection.request(method,path or '/'+self.server.token+'/stream.mp4',body=body,headers=headers or {})
            response=connection.getresponse();return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()
    def test_range_cors_and_origin_token_host_boundaries(self):
        status,headers,data=self.request(headers={'Origin':ORIGIN,'Range':'bytes=10-19'})
        self.assertEqual((status,data),(206,bytes(range(10,20))))
        self.assertEqual(headers['Access-Control-Allow-Origin'],ORIGIN)
        self.assertEqual(headers['Content-Range'],'bytes 10-19/1024')
        for headers in ({},{'Origin':'https://untrusted.invalid'},{'Origin':ORIGIN,'Host':'rebound.invalid'}):
            self.assertIn(self.request(headers=headers)[0],(403,404))
        self.assertEqual(self.request(headers={'Origin':ORIGIN},path='/wrong/stream.mp4')[0],404)
    def test_suspend_blocks_reads_until_explicit_resume(self):
        self.assertEqual(self.request('POST',body=b'suspend')[0],204)
        self.assertEqual(self.request(headers={'Origin':ORIGIN})[0],409)
        self.assertEqual(self.source.reads,0)
        self.assertEqual(self.request('POST',headers={'Origin':ORIGIN},body=b'resume')[0],403)
        self.assertEqual(self.request('POST',body=b'resume')[0],204)
        self.assertEqual(self.request(headers={'Origin':ORIGIN})[0],200)
        self.assertEqual(self.source.reads,1)
    def test_parallel_browser_ranges_do_not_cancel_each_other(self):
        barrier=threading.Barrier(2);read=self.source.read;results=[]
        def overlapping(start,end,cancelled):
            barrier.wait(2)
            yield from read(start,end,cancelled)
        self.source.read=overlapping
        def request():
            try:results.append(self.request(headers={'Origin':ORIGIN,'Range':'bytes=10-19'}))
            except Exception as error:results.append(error)
        workers=[threading.Thread(target=request) for _ in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(3)
        self.assertEqual(len(results),2)
        for result in results:
            self.assertIsInstance(result,tuple)
            self.assertEqual((result[0],result[2]),(206,bytes(range(10,20))))
    def test_old_session_cannot_close_or_checkpoint_new_playback(self):
        account=Mock();account.sync_error=None
        media=Media(account);media.browser=True;media.resource=self.server.address;media.generation=4
        with patch.object(media,'close') as close,patch.object(media,'checkpoint') as checkpoint:
            for method in ('playback.close','playback.checkpoint','playback.suspend'):
                with self.assertRaises(ValueError):media.call(method,dict(session=3,position=1.,duration=8.))
            close.assert_not_called();checkpoint.assert_not_called()
    def test_browser_ready_does_not_start_a_decoder_or_publish_upstream_material(self):
        account=Mock();account.sync_error=None;account.current_identity.return_value=True
        media=Media(account);media.browser=True;media.loading=True;media.metadata=dict(series='123',episode=1)
        media.events.put((media.generation,dict(ok=True,identity_verified=True,series='123',episode=1,episodes=[1],width=640,height=360,
            available_qualities=['360p'],media=self.server.address,resolver=dict(owner='private-owner',catalog=[]),key='SECRET')))
        with patch('lazybuddy_hongguo.media.Job',side_effect=AssertionError('decoder must stay absent')):
            media.pump();state=media.state()
        self.assertTrue(state['prepared']);self.assertIsNone(media.process)
        self.assertEqual(state['resource']['url'],self.server.address)
        self.assertNotIn('resolver',state);self.assertNotIn('key',state)

if __name__=='__main__':unittest.main()
