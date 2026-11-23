"""Only previously received CDN covers may be requested; signed URLs stay private."""
import base64
import hashlib,os,tempfile,time
from pathlib import Path
import struct
import sys
import urllib.parse
import urllib.request
from .jobs import run


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise ValueError('cover_redirect_rejected')


def valid_url(value):
    if not isinstance(value,str) or len(value)>2048:return False
    try:
        uri=urllib.parse.urlsplit(value)
        return (uri.scheme=='https' and uri.hostname and uri.hostname.endswith(('.byteimg.com','.pstatp.com','.fqnovelpic.com'))
                and uri.port in (None,443) and not uri.username and not uri.password and not uri.fragment)
    except ValueError:
        return False


def _download(url,cancelled=None):
    limit=4*1024*1024
    deadline=time.monotonic()+10
    with urllib.request.build_opener(NoRedirect()).open(url,timeout=5) as response:
        if response.status!=200:raise ValueError('cover_unavailable')
        data=bytearray()
        while len(data)<=limit:
            if cancelled is not None and cancelled.is_set():raise ValueError('work_cancelled')
            if time.monotonic()>=deadline:raise ValueError('cover_unavailable')
            chunk=response.read1(min(64*1024,limit+1-len(data)))
            if not chunk:break
            data.extend(chunk)
    if len(data)>limit:raise ValueError('cover_size')
    result=run([sys.executable,'-I','-B',str(Path(__file__).resolve().parent/'backend/cover.py')],
        input=data,timeout=8,memory_limit=384*1024*1024,cancelled=cancelled)
    if result.returncode or not 8<len(result.stdout)<=8+240*360*4:raise ValueError('cover_decode_failed')
    width,height=struct.unpack('>II',result.stdout[:8])
    if not 0<width<=240 or not 0<height<=360 or len(result.stdout)!=8+width*height*4:raise ValueError('cover_decode_failed')
    return dict(width=width,height=height,rgba=base64.b64encode(result.stdout[8:]).decode('ascii'))

MAX_CACHE_FILES=64
MAX_CACHE_AGE=7*24*60*60

def _pixels(data):
    if not 8<len(data)<=8+240*360*4:raise ValueError('cover_cache_invalid')
    width,height=struct.unpack('>II',data[:8])
    if not 0<width<=240 or not 0<height<=360 or len(data)!=8+width*height*4:raise ValueError('cover_cache_invalid')
    return dict(width=width,height=height,rgba=base64.b64encode(data[8:]).decode('ascii'))

def _root():
    directory=os.environ.get('LAZYBUDDY_DATA_DIR')
    return Path(directory)/'cache'/'covers' if directory else None


def _series_key(series):
    if not isinstance(series,str) or not series.isascii() or not series.isdecimal() or not 1<=len(series)<=32 or int(series)==0:raise ValueError('invalid_series')
    return hashlib.sha256(('series:'+series).encode()).hexdigest()


def _cached(path):
    if path:
        try:
            stat=path.stat()
            if stat.st_size<=8+240*360*4 and time.time()-stat.st_mtime<MAX_CACHE_AGE:
                with path.open('rb') as source:return _pixels(source.read(9+240*360*4))
        except (OSError,ValueError):pass
    raise ValueError('cover_unavailable')


def read_cached(series):
    key=_series_key(series);root=_root()
    return _cached(root/('cover-'+key+'.rgba') if root else None)


def read(url,series=None,cancelled=None):
    if not valid_url(url):raise ValueError('invalid_cover')
    root=_root()
    key=_series_key(series) if series is not None else hashlib.sha256(url.encode()).hexdigest()
    path=root/('cover-'+key+'.rgba') if root else None
    try:return _cached(path)
    except ValueError:pass
    if cancelled is not None and cancelled.is_set():raise ValueError('work_cancelled')
    result=_download(url,cancelled) if cancelled is not None else _download(url)
    if cancelled is not None and cancelled.is_set():raise ValueError('work_cancelled')
    if path:
        temporary=None
        try:
            from .backend.lease import acquire
            root.mkdir(parents=True,exist_ok=True)
            data=struct.pack('>II',result['width'],result['height'])+base64.b64decode(result['rgba'],validate=True)
            _pixels(data)
            with acquire(root/'cache.lock',wait=.2) as locked:
                if locked and (cancelled is None or not cancelled.is_set()):
                    with tempfile.NamedTemporaryFile(dir=root,prefix='cover-write-',delete=False) as output:
                        temporary=Path(output.name);output.write(data)
                    os.replace(temporary,path);temporary=None
                    files=sorted((p for p in root.glob('cover-*.rgba') if len(p.stem)==70 and all(c in '0123456789abcdef' for c in p.stem[6:])),key=lambda p:p.stat().st_mtime)
                    for old in files[:-MAX_CACHE_FILES]:old.unlink()
        except (OSError,ValueError):pass
        finally:
            if temporary:
                try:temporary.unlink()
                except OSError:pass
    return result
