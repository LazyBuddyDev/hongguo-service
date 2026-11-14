"""Explicit synthetic service fixture. Never include this entry in release packages."""
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'packages')]
from lazybuddy_hongguo.media import Media
from lazybuddy_hongguo.protocol import Service
from lazybuddy_hongguo.backend.progressive import Server

class Account:
    sync_error=None
    probe=SimpleNamespace(cancel=lambda:None)
    def pending_progress(self):return False

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
        if not browser or args.get('series')!='123' or args.get('episode')!=1 or args.get('origin')!='http://tauri.localhost':raise ValueError('media_request_failed')
        self.close(wait=False)
        data=Path(os.environ['LAZYBUDDY_BROWSER_FIXTURE_FILE']).read_bytes()
        if not 0<len(data)<=8*1024*1024:raise ValueError('media_request_failed')
        self.server=Server(Source(data),origin=args['origin']);self.worker=threading.Thread(target=self.server.serve);self.worker.start()
        self.browser=True;self.suspended=False;self.resource=self.server.address
        self.metadata=dict(series='123',episode=1,episodes=[1],width=640,height=360,available_qualities=['720p'])
        return self.state()
    def close(self,wait=True):
        if self.server:
            self.server.server.shutdown();self.server.close();self.worker.join(2);self.server=self.worker=None
        return super().close(wait)

def main():
    service=Service(Account,media_factory=Fixture)
    try:
        for line in sys.stdin.buffer:
            request=json.loads(line)
            print(json.dumps(service.handle(request),separators=(',',':')),flush=True)
    finally:service.close()

if __name__=='__main__':main()
