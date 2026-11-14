"""Only previously received CDN covers may be requested; signed URLs stay private."""
import base64
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


def read(url):
    if not valid_url(url):raise ValueError('invalid_cover')
    with urllib.request.build_opener(NoRedirect()).open(url,timeout=5) as response:
        if response.status!=200:raise ValueError('cover_unavailable')
        data=response.read(4*1024*1024+1)
    if len(data)>4*1024*1024:raise ValueError('cover_size')
    result=run([sys.executable,'-I','-B',str(Path(__file__).resolve().parent/'backend/cover.py')],
        input=data,timeout=8,memory_limit=384*1024*1024)
    if result.returncode or not 8<len(result.stdout)<=8+240*360*4:raise ValueError('cover_decode_failed')
    width,height=struct.unpack('>II',result.stdout[:8])
    if not 0<width<=240 or not 0<height<=360 or len(result.stdout)!=8+width*height*4:raise ValueError('cover_decode_failed')
    return dict(width=width,height=height,rgba=base64.b64encode(result.stdout[8:]).decode('ascii'))
