"""Fixed App media with offset-preserving sample processing and a bounded Range cache."""
import re,urllib.request,urllib.parse,urllib.error,http.server,http.client,ssl,secrets,threading,bisect,collections
from .media_container import boxes,only,uint,byte_range,Cipher,algorithms,modes
from lazybuddy_hongguo.diagnostics import failure

def allowed(url,source=None):
    try:
        u=urllib.parse.urlsplit(url)
        if not (u.scheme=='https' and u.hostname and u.port in (None,443) and not u.username and not u.password and not u.fragment):return False
        if u.hostname.endswith('.qznovelvod.com'):return True
        if not source:return False
        previous=urllib.parse.urlsplit(source)
        if not allowed(source):return False
        # Numbered media origins share scheduling; qualified CDN nodes remain redirect-only.
        return bool(re.fullmatch(r'v[0-9]+-reading-video(?:-[a-z]|cdn(?:302)?)?\.qznovelvod\.com',previous.hostname)
            and re.fullmatch(r'(?:[a-z0-9]{40,64}\.vegslb\.com|[a-f0-9]{40,64}\.v\.smtcdns\.com)',u.hostname))
    except ValueError:return False
class Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,context=None,source=None):self.context,self.source=context,source
    def redirect_request(self,req,fp,code,msg,headers,url):
        check_redirect(url,context=self.context,status=code,source=self.source or req.full_url)
        return super().redirect_request(req,fp,code,msg,headers,url)

def check_redirect(url,**details):
    if not allowed(url,details.get('source')):
        reason='media_redirect_https_required' if url.lower().startswith('http:') else 'media_redirect_target_rejected'
        raise failure(reason,stage='redirect',target=url,**details)

class Source:
    context=None
    BLOCK=256*1024
    INITIAL=64*1024
    def __init__(self,url,key,context=None):
        if not allowed(url) or (key is not None and len(key)!=16):raise ValueError('invalid_media_source')
        self.url,self.key=url,key;self.total=None;self.downloaded=0;self.requests=0;self.denied=False;self.error=None
        self.context=context
        self.connection=None;self.origin=None;self.tls=ssl.create_default_context()
        self.proxy=bool(urllib.request.getproxies().get('https'))
        self.opener=urllib.request.build_opener(Redirect(context,url),urllib.request.HTTPSHandler(context=self.tls))
        self.lock=threading.Lock();self.cache=collections.OrderedDict();self.spans=[];self.tracks=set()
        prefix=self.fetch(0,self.INITIAL-1)
        top=[];pos=0
        while pos+8<=self.total:
            if len(top)>=64:raise ValueError('metadata_limit')
            header=prefix[pos:pos+16] if pos+16<=len(prefix) else self.fetch(pos,min(pos+15,self.total-1))
            size=int.from_bytes(header[:4],'big');kind=header[4:8];header_size=8
            if size==1:
                if len(header)<16:raise ValueError('invalid_media_box')
                size=int.from_bytes(header[8:16],'big');header_size=16
            if size==0:size=self.total-pos
            if size<header_size or pos+size>self.total:raise ValueError('unsupported_top_level_box')
            top.append((kind,pos,pos+header_size,pos+size))
            if kind==b'moov' and pos+size>len(prefix):
                if pos+size>1024*1024 or header_size!=8:raise ValueError('metadata_limit')
                prefix+=self.fetch(len(prefix),min(pos+size+16,self.total)-1)
            pos+=size
        moov=only(top,b'moov');self.moov_offset=moov[1];self.moov=bytearray(prefix[moov[1]:moov[3]])
        mdats=[(p,e) for kind,_,p,e in top if kind==b'mdat']
        if not mdats:raise ValueError('unsupported_media_layout')
        for kind,_,p,e in boxes(self.moov,8):
            if kind==b'pssh':self.moov[p-4:p]=b'free'
            if kind==b'trak':self.track(p,e,mdats)
        if self.tracks!={'video','audio'}:raise ValueError('unsupported_media_layout')
        self.spans.sort(key=lambda s:s[0])
        if any(a[1]>b[0] for a,b in zip(self.spans,self.spans[1:])):raise ValueError('invalid_sample_spans')
        self.ends=[s[1] for s in self.spans]
        for start in range(0,len(prefix),self.BLOCK):
            self.cache[start]=self.clear(start,prefix[start:start+self.BLOCK])
    def fetch(self,start,end):
        if self.denied:raise ValueError('media_access_denied')
        try:return self.fetch_range(start,end)
        except urllib.error.HTTPError as error:
            if error.code in (401,403):self.denied=True;reason='media_access_denied'
            elif error.code in (301,302,303,307,308):reason='media_redirect_limit' if error.headers.get('Location') else 'media_redirect_missing_location'
            else:reason='media_http_error'
            raise failure(reason,stage='range',context=self.context,status=error.code,source=self.url,mode='proxy' if self.proxy else 'direct') from None
        except (urllib.error.URLError,OSError,http.client.HTTPException) as error:
            raise failure('media_network_error',stage='range',context=self.context,source=self.url,mode='proxy' if self.proxy else 'direct',exception_type=type(getattr(error,'reason',error)).__name__) from None
    def fetch_range(self,start,end):
        request=urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'})
        with self.open_range(request) as response:
            match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status!=206 or not match:raise ValueError('range_not_supported')
            lo,hi,total=map(int,match.groups())
            if lo!=start or hi!=min(end,total-1) or not 0<total<=128*1024*1024 or (self.total is not None and total!=self.total):raise ValueError('invalid_content_range')
            size=hi-lo+1
            if size>1024*1024:raise ValueError('range_limit')
            data=response.read(size+1)
            if len(data)!=size:raise ValueError('incomplete_media_range')
            self.total=total;self.downloaded+=len(data);self.requests+=1
            return data
    def open_range(self,request):
        if self.proxy:return self.opener.open(request,timeout=8)
        url=request.full_url
        for hop in range(6):
            check_redirect(url,context=self.context,source=self.url,hop=hop,mode='direct')
            parsed=urllib.parse.urlsplit(url);origin=(parsed.hostname,parsed.port or 443)
            reused=self.connection is not None and self.origin==origin and self.connection.sock is not None
            if self.connection is None or self.origin!=origin:
                if self.connection is not None:self.connection.close()
                self.connection=http.client.HTTPSConnection(*origin,timeout=8,context=self.tls);self.origin=origin
            try:
                self.connection.request('GET',urllib.parse.urlunsplit(('', '',parsed.path or '/',parsed.query,'')),headers=dict(request.header_items())|{'User-Agent':'Python-urllib/'+urllib.request.__version__})
                response=self.connection.getresponse()
            except (http.client.RemoteDisconnected,BrokenPipeError,ConnectionResetError):
                self.connection.close();self.connection=None
                if reused:return self.open_range(request)
                raise urllib.error.URLError('media_transport_failed') from None
            except (OSError,http.client.HTTPException):
                self.connection.close();self.connection=None
                raise urllib.error.URLError('media_transport_failed') from None
            if response.status in (301,302,303,307,308):
                location=response.headers.get('Location');response.close();self.connection.close();self.connection=None
                if not location:
                    raise failure('media_redirect_missing_location',stage='redirect',context=self.context,status=response.status,hop=hop,source=url,mode='direct')
                url=urllib.parse.urljoin(url,location);continue
            if response.status>=400:
                status,headers=response.status,response.headers;response.close();self.connection.close();self.connection=None
                raise urllib.error.HTTPError(url,status,'media_rejected',headers,None)
            return response
        raise failure('media_redirect_limit',stage='redirect',context=self.context,source=self.url,target=url,hop=6,mode='direct')
    def track(self,start,end,mdats):
        data=self.moov
        def child(start,end,typ):return only(list(boxes(data,start,end)),typ)
        mdia=child(start,end,b'mdia');minf=child(mdia[2],mdia[3],b'minf');stbl=child(minf[2],minf[3],b'stbl');table=list(boxes(data,stbl[2],stbl[3]))
        stsd=only(table,b'stsd');entries=list(boxes(data,stsd[2]+8,stsd[3]))
        if uint(data,stsd[2]+4,4,stsd[3])!=1 or len(entries)!=1:raise ValueError('unsupported_sample_description')
        typ,begin,p,e=entries[0]
        if typ in (b'encv',b'avc1',b'hvc1',b'hev1'):self.tracks.add('video')
        elif typ in (b'enca',b'mp4a'):self.tracks.add('audio')
        else:raise ValueError('unsupported_media_codec')
        if typ not in (b'encv',b'enca'):return
        if self.key is None:raise ValueError('missing_content_key')
        extra=78 if typ==b'encv' else 28
        if typ==b'enca' and uint(data,p+8,2,e)!=0:raise ValueError('unsupported_audio_entry')
        sinf=child(p+extra,e,b'sinf');frma=child(sinf[2],sinf[3],b'frma');schm=child(sinf[2],sinf[3],b'schm');schi=child(sinf[2],sinf[3],b'schi');tenc=child(schi[2],schi[3],b'tenc')
        original=bytes(data[frma[2]:frma[3]])
        if original not in (b'avc1',b'hvc1',b'hev1',b'mp4a'):raise ValueError('unsupported_media_codec')
        if data[schm[2]+4:schm[2]+8]!=b'cenc':raise ValueError('unsupported_protection')
        tp=tenc[2]
        if tenc[3]-tp!=24 or data[tp:tp+7]!=b'\0\0\0\0\0\0\1' or data[tp+7] not in (8,16):raise ValueError('unsupported_track_encryption')
        ivsize=data[tp+7]
        if any(t in (b'sbgp',b'sgpd') and data[p+4:p+8]==b'seig' for t,_,p,_ in table):raise ValueError('unsupported_encryption_groups')
        stsz=only(table,b'stsz');p,e=stsz[2:];default=uint(data,p+4,4,e);count=uint(data,p+8,4,e)
        if not 0<count<=1000000 or (default==0 and p+12+4*count!=e):raise ValueError('invalid_sample_sizes')
        sizes=[default]*count if default else [uint(data,p+12+i*4,4,e) for i in range(count)]
        stsc=only(table,b'stsc');p,e=stsc[2:];n=uint(data,p+4,4,e)
        if not 0<n<=count or p+8+n*12!=e:raise ValueError('invalid_chunk_map')
        runs=[tuple(uint(data,p+8+i*12+j*4,4,e) for j in range(3)) for i in range(n)]
        if runs[0][0]!=1 or any(a[0]>=b[0] for a,b in zip(runs,runs[1:])) or any(v==0 or d!=1 for _,v,d in runs):raise ValueError('unsupported_chunk_map')
        offsets=[t for t in table if t[0] in (b'stco',b'co64')]
        if len(offsets)!=1:raise ValueError('invalid_chunk_offsets')
        typ,_,p,e=offsets[0];width=4 if typ==b'stco' else 8;chunks=uint(data,p+4,4,e)
        if not 0<chunks<=count or p+8+chunks*width!=e:raise ValueError('invalid_chunk_offsets')
        samples=[];index=0;run=0
        for chunk in range(1,chunks+1):
            while run+1<len(runs) and runs[run+1][0]<=chunk:run+=1
            offset=uint(data,p+8+(chunk-1)*width,width,e)
            for _ in range(runs[run][1]):
                if index>=count or sizes[index]==0:raise ValueError('invalid_sample_count')
                size=sizes[index]
                if not any(lo<=offset and offset+size<=hi for lo,hi in mdats):raise ValueError('sample_outside_media')
                samples.append((offset,size));offset+=size;index+=1
        if index!=count:raise ValueError('invalid_sample_count')
        senc=only(table,b'senc');p,e=senc[2:];flags=uint(data,p,4,e)
        if flags not in (0,2) or uint(data,p+4,4,e)!=count:raise ValueError('unsupported_sample_encryption')
        p+=8
        for offset,size in samples:
            if p+ivsize>e:raise ValueError('invalid_sample_iv')
            iv=bytes(data[p:p+ivsize])+b'\0'*(16-ivsize);p+=ivsize
            spans=[(0,size)]
            if flags==2:
                n=uint(data,p,2,e);p+=2;spans=[]
                for _ in range(n):spans.append((uint(data,p,2,e),uint(data,p+2,4,e)));p+=6
            pos=0;encrypted_offset=0
            for clear,encrypted in spans:
                pos+=clear
                if pos+encrypted>size:raise ValueError('invalid_sample_subrange')
                if encrypted:self.spans.append((offset+pos,offset+pos+encrypted,iv,encrypted_offset))
                pos+=encrypted;encrypted_offset+=encrypted
            if pos!=size:raise ValueError('invalid_sample_subrange')
        if p!=e:raise ValueError('invalid_sample_encryption_size')
        data[begin+4:begin+8]=original;data[sinf[1]+4:sinf[1]+8]=b'free'
        for typ,begin,_,_ in table:
            if typ in (b'senc',b'saio',b'saiz'):data[begin+4:begin+8]=b'free'
    def clear(self,start,data):
        out=bytearray(data);end=start+len(out)
        lo=max(start,self.moov_offset);hi=min(end,self.moov_offset+len(self.moov))
        if lo<hi:out[lo-start:hi-start]=self.moov[lo-self.moov_offset:hi-self.moov_offset]
        for a,b,iv,offset in self.spans[bisect.bisect_right(self.ends,start):]:
            if a>=end:break
            lo=max(start,a);hi=min(end,b);offset+=lo-a
            counter=(int.from_bytes(iv,'big')+offset//16)%(1<<128)
            cipher=Cipher(algorithms.AES(self.key),modes.CTR(counter.to_bytes(16,'big'))).decryptor()
            cipher.update(b'\0'*(offset%16))
            out[lo-start:hi-start]=cipher.update(out[lo-start:hi-start]);cipher.finalize()
        return bytes(out)
    def read(self,start,end,cancelled=lambda:False):
        while start<=end:
            if cancelled():return
            block=start//self.BLOCK*self.BLOCK
            with self.lock:
                if cancelled():return
                value=self.cache.get(block,b'')
                if start-block>=len(value):
                    at=block+len(value)
                    stop=min(block+self.BLOCK,self.total)
                    if value:stop=min(stop,max(at,start)+self.INITIAL)
                    fetched=self.clear(at,self.fetch(at,stop-1))
                    if cancelled():return
                    value+=fetched;self.cache[block]=value
                    while len(self.cache)>8:self.cache.popitem(last=False)
                self.cache.move_to_end(block)
                size=min(end-start+1,len(value)-(start-block));result=value[start-block:start-block+size]
            if cancelled():return
            yield result;start+=size
    def warmup(self):
        # One bounded startup buffer, retained only in the existing memory cache.
        for _ in self.read(0,min(self.total,1024*1024)-1):pass

    def stats(self):
        with self.lock:return {'file_bytes':self.total,'downloaded_bytes':self.downloaded,'metadata_bytes':len(self.moov),'cache_bytes':sum(map(len,self.cache.values())),'cache_limit':8*self.BLOCK,'range_requests':self.requests,'samples_encrypted':len(self.spans)}

class Server:
    def __init__(self,source,on_error=None,origin=None):
        self.source=source;self.origin=origin;self.active=True;self.token=secrets.token_urlsafe(32);self.generation=0;self.reader_lock=threading.Lock();self.error_lock=threading.Lock();self.error_notified=False;owner=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def setup(self):
                super().setup();self.connection.settimeout(5)
            def log_message(self,*_):pass
            def do_HEAD(self):self.respond(False)
            def do_GET(self):self.respond(True)
            def target(self):return self.headers.get('Host')==owner.host and self.path=='/'+owner.token+'/stream.mp4'
            def cors(self):
                if owner.origin:
                    self.send_header('Access-Control-Allow-Origin',owner.origin);self.send_header('Vary','Origin')
                    self.send_header('Access-Control-Expose-Headers','Content-Length, Content-Range, Accept-Ranges')
            def do_OPTIONS(self):
                if not self.target() or not owner.origin or self.headers.get('Origin')!=owner.origin:self.send_error(403);return
                self.send_response(204);self.cors();self.send_header('Access-Control-Allow-Methods','GET, HEAD');self.send_header('Access-Control-Allow-Headers','Range')
                if self.headers.get('Access-Control-Request-Private-Network')=='true':self.send_header('Access-Control-Allow-Private-Network','true')
                self.send_header('Content-Length','0');self.end_headers()
            def do_POST(self):
                # Only the owning local service controls a stream. Browsers get read access.
                if not self.target() or self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site'):self.send_error(403);return
                if self.headers.get('Content-Length') not in ('6','7'):self.send_error(400);return
                command=self.rfile.read(int(self.headers['Content-Length']))
                if command not in (b'suspend',b'resume'):self.send_error(400);return
                with owner.reader_lock:owner.active=command==b'resume';owner.generation+=1
                self.send_response(204);self.send_header('Content-Length','0');self.end_headers()
            def respond(self,body):
                if not self.target():self.send_error(404);return
                if owner.origin and self.headers.get('Origin')!=owner.origin:self.send_error(403);return
                if not owner.active:self.send_error(409);return
                try:lo,hi=byte_range(self.headers.get('Range'),source.total)
                except ValueError:self.send_error(416);return
                if body:
                    with owner.reader_lock:
                        # Browsers can concurrently read an index and media range.
                        # Only lifecycle changes invalidate browser reads.
                        if owner.origin is None:owner.generation+=1
                        generation=owner.generation
                partial=self.headers.get('Range') is not None
                self.send_response(206 if partial else 200);self.cors();self.send_header('Content-Length',str(hi-lo+1));self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store');self.send_header('Connection','close')
                if partial:self.send_header('Content-Range',f'bytes {lo}-{hi}/{source.total}')
                self.end_headers()
                if body:
                    try:
                        for data in source.read(lo,hi,lambda:generation!=owner.generation or not owner.active):self.wfile.write(data)
                    except OSError:pass
                    except ValueError as error:
                        source.error=str(error)
                        with owner.error_lock:
                            if on_error and not owner.error_notified:owner.error_notified=True;on_error(error)
                self.close_connection=True
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.host=f'127.0.0.1:{self.server.server_port}';self.address='http://'+self.host+'/'+self.token+'/stream.mp4'
    def serve(self):self.server.serve_forever()
    def close(self):
        self.active=False;self.generation+=1
        self.server.server_close()
        if getattr(self.source,'connection',None) is not None:self.source.connection.close()
