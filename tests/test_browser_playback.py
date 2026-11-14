"""Browser resource access and lifecycle, using memory data and localhost only."""
import http.client
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
