"""Explicit synthetic service fixture. Never include this entry in release packages."""
import json
import os
from pathlib import Path
import sys
import threading
import struct,zlib
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'packages')]
from lazybuddy_hongguo.media import Media
from lazybuddy_hongguo.protocol import Service
from lazybuddy_hongguo.backend.progressive import Server

class Account:
    sync_error=None
    probe=SimpleNamespace(cancel=lambda:None)
    def __init__(self):self.state='idle';self.polls=0;self.favorites=[]
    def pending_progress(self):return False
    def call(self,request):
        command=request['command']
        if command=='login':self.state='pending';self.polls=0
        if command in ('cancel','logout'):self.state='idle';self.favorites=[]
        if command=='status' and self.state=='pending':
            self.polls+=1
            if self.polls>=3:self.state='signed_in'
        if command=='favorites':self.favorites=[dict(id='123',title='测试短剧',episodes=1)]
        if command=='favorite_set':self.favorites=[dict(id='123',title='测试短剧',episodes=1)] if request['favorite'] else []
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0\xff'))+chunk(b'IEND',b'')
        return dict(state=self.state,name='样例用户' if self.state=='signed_in' else '',qr=png if self.state=='pending' else b'',favorites=self.favorites,history={},error=None)

class Source:
    connection=None
    def __init__(self,data):self.data=data;self.total=len(data);self.reads=0
    def read(self,start,end,cancelled):
        for at in range(start,end+1,256*1024):
            if cancelled():return
            self.reads+=1
            yield self.data[at:min(at+256*1024,end+1)]

class Fixture(Media):
    def __init__(self,account):super().__init__(account);self.server=self.worker=None
    def open(self,args,browser=False):
        if not browser or args.get('series') not in ('123','124') or args.get('episode')!=1 or args.get('origin')!='http://tauri.localhost':raise ValueError('media_request_failed')
        if args.get('quality') not in ('360p','480p','720p','1080p'):raise ValueError('invalid_quality')
        if args['series']=='124' and args['quality']!='720p':raise ValueError('quality_unavailable')
        self.close(wait=False)
        data=Path(os.environ['LAZYBUDDY_BROWSER_FIXTURE_FILE']).read_bytes()
        if not 0<len(data)<=8*1024*1024:raise ValueError('media_request_failed')
        self.server=Server(Source(data),origin=args['origin']);self.worker=threading.Thread(target=self.server.serve);self.worker.start()
        self.browser=True;self.suspended=False;self.resource=self.server.address
        self.metadata=dict(series=args['series'],episode=1,episodes=[1],width=640,height=360,available_qualities=[360,720,1080])
        return self.state()
    def close(self,wait=True):
        if self.server:
            self.server.server.shutdown();self.server.close();self.worker.join(2);self.server=self.worker=None
        return super().close(wait)

def main():
    def search(request):return dict(version=1,id=request['id'],ok=True,data=dict(items=[dict(id='123',title='测试短剧',episodes=1),dict(id='124',title='另一部短剧',episodes=1)],page=1,has_more=False))
    service = Service(Account,search_factory=search,media_factory=Fixture)
    try:
        for line in sys.stdin.buffer:
            request=json.loads(line)
            print(json.dumps(service.handle(request),separators=(',',':')),flush=True)
    finally:service.close()

if __name__=='__main__':main()
