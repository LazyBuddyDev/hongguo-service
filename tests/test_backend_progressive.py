import sys
from pathlib import Path
"""Synthetic MP4, partial CTR ranges, cache bounds and private loopback checks."""
import pathlib,sys,unittest,urllib.error
from unittest.mock import patch,Mock
from lazybuddy_hongguo.backend import progressive as m

def box(kind,body):return (8+len(body)).to_bytes(4,'big')+kind+body
def u32(value):return value.to_bytes(4,'big')
def fixture(ivsize=8,subsamples=False,padding=0,metadata_padding=0):
    key=b'\x11'*16;clear=b'lead-'+bytes(range(256))*4+b' end';iv=bytes(range(ivsize));counter=iv+b'\0'*(16-ivsize)
    spans=[(5,19),(7,len(clear)-31)] if subsamples else [(0,len(clear))]
    cipher=m.Cipher(m.algorithms.AES(key),m.modes.CTR(counter)).encryptor();encoded=bytearray(clear);pos=0
    for lead,size in spans:pos+=lead;encoded[pos:pos+size]=cipher.update(encoded[pos:pos+size]);pos+=size
    cipher.finalize()
    def track(offset,audio):
        tenc=box(b'tenc',b'\0'*4+b'\0\0\1'+bytes([ivsize])+b'\0'*16)
        sinf=box(b'sinf',box(b'frma',b'mp4a' if audio else b'hvc1')+box(b'schm',b'\0'*4+b'cenc'+b'\0'*4)+box(b'schi',tenc))
        entry=box(b'enca' if audio else b'encv',b'\0'*(28 if audio else 78)+sinf)
        senc=u32(2 if subsamples else 0)+u32(1)+iv
        if subsamples:senc+=len(spans).to_bytes(2,'big')+b''.join(a.to_bytes(2,'big')+u32(b) for a,b in spans)
        stbl=box(b'stsd',b'\0'*4+u32(1)+entry)+box(b'stsz',b'\0'*4+u32(0)+u32(1)+u32(len(clear)))+box(b'stsc',b'\0'*4+u32(1)+u32(1)+u32(1)+u32(1))+box(b'stco',b'\0'*4+u32(1)+u32(offset))+box(b'senc',senc)+box(b'sbgp',b'\0'*4+b'roll'+u32(0))
        return box(b'trak',box(b'mdia',box(b'minf',box(b'stbl',stbl))))
    extra=box(b'free',b'\0'*metadata_padding)
    ftyp=box(b'ftyp',b'isom'+b'\0'*4);moov=box(b'moov',extra+track(0,False)+track(0,True));offset=len(ftyp)+len(moov)+8
    moov=box(b'moov',extra+track(offset,False)+track(offset+len(clear),True))
    return ftyp+moov+box(b'mdat',bytes(encoded)*2+b'\0'*padding),clear,key,offset

class FakeSource(m.Source):
    def __init__(self,data,key):self.data=data;super().__init__('https://fixture.qznovelvod.com/a',key)
    def fetch(self,start,end):
        value=self.data[start:end+1];self.total=len(self.data);self.downloaded+=len(value);self.requests+=1;return value

class Tests(unittest.TestCase):
    def test_fetch_finishing_after_suspend_does_not_populate_cache(self):
        data,_,key,_=fixture(padding=1024*1024);source=FakeSource(data,key)
        before=dict(source.cache);cancelled=False;fetch=source.fetch
        def late(start,end):
            nonlocal cancelled
            value=fetch(start,end);cancelled=True;return value
        source.fetch=late
        self.assertEqual(list(source.read(source.BLOCK,source.BLOCK+9,lambda:cancelled)),[])
        self.assertEqual(dict(source.cache),before)
    def test_partial_startup_block_extends_without_changing_ctr_offsets(self):
        data,clear,key,offset=fixture(metadata_padding=64000,padding=1024*1024)
        source=FakeSource(data,key)
        self.assertLess(source.downloaded,source.BLOCK)
        self.assertLess(len(source.cache[0]),source.BLOCK)
        self.assertEqual(b''.join(source.read(offset,offset+len(clear)*2-1)),clear*2)
        self.assertEqual(b''.join(source.read(240000,240031)),data[240000:240032])
        self.assertLessEqual(source.stats()['cache_bytes'],2*1024*1024)
    def test_stale_keepalive_reconnects_once_but_never_retries_a_fresh_failure(self):
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.origin=('fixture.qznovelvod.com',443);source.proxy=False;source.tls=None
        old=Mock();old.getresponse.side_effect=m.http.client.RemoteDisconnected();source.connection=old
        fresh=Mock();reply=Mock(status=206);fresh.getresponse.return_value=reply
        with patch.object(m.http.client,'HTTPSConnection',return_value=fresh) as factory:
            self.assertIs(source.open_range(m.urllib.request.Request(source.url)),reply)
            self.assertEqual(factory.call_count,1);self.assertEqual(old.request.call_count,1)
        source.connection=None;fresh.getresponse.side_effect=m.http.client.RemoteDisconnected()
        with patch.object(m.http.client,'HTTPSConnection',return_value=fresh) as factory:
            with self.assertRaises(m.urllib.error.URLError):source.open_range(m.urllib.request.Request(source.url))
            self.assertEqual(factory.call_count,1)
    def test_keepalive_403_is_terminal_without_reconnect(self):
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.origin=('fixture.qznovelvod.com',443);source.proxy=False;source.tls=None;source.denied=False
        connection=Mock();connection.getresponse.return_value=Mock(status=403,headers={});source.connection=connection
        with patch.object(m.http.client,'HTTPSConnection') as factory:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'media_access_denied'):source.fetch(0,3)
            factory.assert_not_called();self.assertEqual(connection.request.call_count,1)
    def test_ranges_reuse_tls_connection_with_identical_range_validation(self):
        import io,ssl
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.connection=None;source.origin=None;source.proxy=False;source.tls=ssl.create_default_context();source.total=None;source.downloaded=source.requests=0
        replies=[]
        for lo in (0,4):
            reply=Mock();reply.status=206;reply.headers={'Content-Range':f'bytes {lo}-{lo+3}/8'};reply.read=io.BytesIO(b'abcd').read;reply.__enter__=Mock(return_value=reply);reply.__exit__=Mock(return_value=False);replies.append(reply)
        connection=Mock();connection.getresponse.side_effect=replies
        with patch.object(m.http.client,'HTTPSConnection',return_value=connection) as factory:
            self.assertEqual(source.fetch_range(0,3),b'abcd');self.assertEqual(source.fetch_range(4,7),b'abcd')
            self.assertEqual(factory.call_count,1);self.assertEqual(source.requests,2)
            self.assertTrue(factory.call_args.kwargs['context'].check_hostname);self.assertEqual(factory.call_args.kwargs['context'].verify_mode,ssl.CERT_REQUIRED)
    def test_keepalive_redirect_cannot_leave_media_allowlist(self):
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.connection=None;source.origin=None;source.proxy=False;source.tls=None
        reply=Mock(status=302,headers={'Location':'https://untrusted.invalid/a'});connection=Mock();connection.getresponse.return_value=reply
        with patch.object(m.http.client,'HTTPSConnection',return_value=connection) as factory:
            with self.assertRaisesRegex(ValueError,'media_redirect_target_rejected'):source.open_range(m.urllib.request.Request(source.url))
            self.assertEqual(factory.call_count,1);self.assertEqual(connection.request.call_count,1)
    def test_redirect_failures_keep_distinct_safe_codes(self):
        from lazybuddy_hongguo.errors import code
        for target,expected in [('http://fixture.qznovelvod.com/a','media_redirect_https_required'),('https://example.invalid/secret?token=fixture','media_redirect_target_rejected')]:
            with self.assertRaises(ValueError) as error:m.check_redirect(target)
            self.assertEqual(code(error.exception),expected)
            self.assertNotIn('token',str(error.exception))
        for location,expected in [(None,'media_redirect_missing_location'),('/a','media_redirect_limit')]:
            source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.connection=None;source.origin=None;source.proxy=False;source.tls=None
            reply=Mock(status=302,headers={} if location is None else {'Location':location});connection=Mock();connection.getresponse.return_value=reply
            with patch.object(m.http.client,'HTTPSConnection',return_value=connection):
                with self.assertRaises(ValueError) as error:source.open_range(m.urllib.request.Request(source.url))
                self.assertEqual(code(error.exception),expected)
                self.assertLessEqual(connection.request.call_count,6)
    def test_approved_redirect_preserves_range_and_reaches_media(self):
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.connection=None;source.origin=None;source.proxy=False;source.tls=None
        redirect=Mock(status=302,headers={'Location':'https://other.qznovelvod.com/b'});media=Mock(status=206)
        first=Mock();first.getresponse.return_value=redirect;second=Mock();second.getresponse.return_value=media
        with patch.object(m.http.client,'HTTPSConnection',side_effect=[first,second]):
            result=source.open_range(m.urllib.request.Request(source.url,headers={'Range':'bytes=0-63'}))
            self.assertIs(result,media)
            self.assertEqual(second.request.call_args.kwargs['headers']['Range'],'bytes=0-63')
    def test_proxy_redirect_errors_have_same_categories_without_retry(self):
        for headers,expected in [({},'media_redirect_missing_location'),({'Location':'https://fixture.qznovelvod.com/a'},'media_redirect_limit')]:
            source=m.Source.__new__(m.Source);source.denied=False
            with patch.object(source,'fetch_range',side_effect=urllib.error.HTTPError('https://fixture.qznovelvod.com/a',302,'fixture',headers,None)) as fetch:
                with self.assertRaisesRegex(ValueError,expected):source.fetch(0,1)
                self.assertEqual(fetch.call_count,1)
    def test_cancelled_range_stops_before_fetching_another_block(self):
        data,_,key,_=fixture(padding=4*1024*1024);source=FakeSource(data,key);cancelled=False
        reader=source.read(0,len(data)-1,lambda:cancelled)
        next(reader);before=source.requests;cancelled=True
        self.assertEqual(list(reader),[]);self.assertEqual(source.requests,before)

    def test_new_get_cancels_old_stream_but_head_does_not(self):
        import http.client,threading
        started=threading.Event();release=threading.Event();stopped=threading.Event()
        class Source:
            total=8
            def read(self,start,end,cancelled):
                if start==0:
                    yield b'AAAA';started.set();release.wait(2)
                    if cancelled():stopped.set();return
                yield b'BBBB'
        server=m.Server(Source());worker=threading.Thread(target=server.serve,daemon=True);worker.start()
        first=http.client.HTTPConnection(server.host,timeout=2);second=http.client.HTTPConnection(server.host,timeout=2)
        path='/'+server.token+'/stream.mp4'
        try:
            first.request('GET',path,headers={'Range':'bytes=0-7'});response=first.getresponse();self.assertEqual(response.read(4),b'AAAA');self.assertTrue(started.wait(2))
            second.request('HEAD',path);head=second.getresponse();head.read();self.assertEqual(server.generation,1)
            second.request('GET',path,headers={'Range':'bytes=4-7'});self.assertEqual(second.getresponse().read(),b'BBBB')
            release.set();self.assertTrue(stopped.wait(2))
        finally:
            release.set();first.close();second.close();server.server.shutdown();server.close();worker.join(2)
    def test_large_metadata_still_discovers_mdat_without_downloading_it(self):
        data,clear,key,offset=fixture(metadata_padding=300000,padding=300000)
        source=FakeSource(data,key)
        self.assertEqual(b''.join(source.read(offset,offset+len(clear)-1)),clear)
        self.assertLess(source.downloaded,len(data))
    def test_partial_subsample_ctr_and_unchanged_offsets(self):
        for iv in (8,16):
            for sub in (False,True):
                data,clear,key,offset=fixture(iv,sub);source=FakeSource(data,key)
                for start,end in [(0,len(clear)),(3,73),(17,89),(29,65)]:
                    self.assertEqual(source.clear(offset+start,data[offset+start:offset+end]),clear[start:end])
                value=b''.join(source.read(offset,offset+len(clear)*2-1))
                self.assertEqual(value,clear*2);self.assertEqual(len(source.moov),int.from_bytes(source.moov[:4],'big'))
                self.assertNotIn(b'encv',source.moov);self.assertNotIn(b'senc',source.moov)
    def test_cache_is_bounded_and_seeks_do_not_read_every_block(self):
        data,clear,key,offset=fixture(padding=4*1024*1024);source=FakeSource(data,key)
        b''.join(source.read(3*1024*1024,3*1024*1024+9))
        self.assertEqual(source.requests,2)
        for block in range(1,14):b''.join(source.read(block*source.BLOCK,block*source.BLOCK+7))
        self.assertLessEqual(source.stats()['cache_bytes'],2*1024*1024)
    def test_key_groups_and_sample_offsets_fail_closed(self):
        data,_,key,_=fixture()
        for corrupted in (data.replace(b'roll',b'seig'),data.replace(b'cenc',b'cbcs')):
            with self.assertRaises(ValueError):FakeSource(corrupted,key)
        data=bytearray(data);at=data.index(b'stco');data[at+12:at+16]=u32(len(data)+1)
        with self.assertRaises(ValueError):FakeSource(bytes(data),key)
    def test_403_is_not_retried_by_later_ranges(self):
        source=m.Source.__new__(m.Source);source.url='https://fixture.qznovelvod.com/a';source.denied=False
        with patch.object(source,'open_range',side_effect=urllib.error.HTTPError('https://fixture.invalid',403,'blocked',{},None)) as open_range:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'media_access_denied'):source.fetch(0,31)
        self.assertEqual(open_range.call_count,1)

if __name__=='__main__':unittest.main()
