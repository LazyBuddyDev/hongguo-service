"""Cancellable private input, separate decoding and account-bound checkpoints."""
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import secrets
from .jobs import Job
from .errors import code


class Media:
    def __init__(self,account):
        self.account=account
        self.process=self.decoder_job=self.decoder_reader=None
        self.input_process=self.input_job=self.input_reader=None
        self.replies=queue.Queue(maxsize=1)
        self.events=queue.SimpleQueue()
        # Exact in JavaScript, unique across restarted service processes.
        self.generation=secrets.randbelow(1<<48)
        self.resolver=None
        self.metadata={}
        self.arguments={}
        self.loading=False
        self.error=None
        self.diagnostic=None
        self.local_error=None
        self.pending_play=False
        self.recorded=None
        self.last_saved=time.monotonic()
        self.flush_guard=threading.Lock()
        self.flush_thread=None
        self.flush_again=False
        self.browser=False
        self.resource=None
        self.suspended=False
        self.browser_final=None
        self.next_media=None

    def call(self,method,args):
        if method.startswith('playback.'):return self.playback(method,args)
        if method=='media.open':return self.open(args)
        if method=='media.close':
            self.close(wait=False)
            return self.state()
        self.pump()
        if method=='media.play' and self.loading:
            self.pending_play=True
            return self.state()
        if method=='media.pause' and self.loading:
            self.pending_play=False
            return self.state()
        if method=='media.status':
            state=self.state()
            if state.get('playing') and time.monotonic()-self.last_saved>=15:self.checkpoint(state)
            return dict(state,progress_error=self.local_error or self.account.sync_error)
        if self.process is None:raise ValueError('media_not_loaded')
        state=self.request(method.removeprefix('media.'),args)
        if method=='media.pause':self.checkpoint(state);self.flush()
        return dict(self.metadata,**state,progress_error=self.local_error or self.account.sync_error)

    def playback(self,method,args):
        if method=='playback.open':return self.open(args,browser=True)
        self.pump()
        if not self.browser:raise ValueError('media_not_loaded')
        if method!='playback.status' and (type(args.get('session')) is not int or args['session']!=self.generation):raise ValueError('media_not_loaded')
        if method=='playback.prefetch':return self.prefetch()
        if method=='playback.prefetch_cancel':self.cancel_prefetch(preserve_failure=True);return self.state()
        if method=='playback.report_error':
            if type(args.get('code')) is not int or args['code'] not in (1,2,3,4):raise ValueError('media_request_failed')
            from .diagnostics import describe
            self.diagnostic=describe('browser_media_error',stage='browser',context={**self.metadata,'quality':self.arguments.get('quality')},browser_code=args['code'])
            return self.state()
        if method=='playback.close':self.close(wait=False);return self.state()
        if method=='playback.status':return self.state()
        if method=='playback.checkpoint':
            if 'final' in args and type(args['final']) is not bool:raise ValueError('media_request_failed')
            position,duration=args.get('position'),args.get('duration')
            if any(type(value) not in (int,float) or not math.isfinite(value) for value in (position,duration)) or not 0<duration<=86400 or not 0<=position<=duration:raise ValueError('media_request_failed')
            if not self.resource:raise ValueError('media_not_loaded')
            self.checkpoint(dict(position=position,duration=duration))
            if args.get('final') and self.recorded!=self.browser_final:
                self.browser_final=self.recorded;self.flush()
            return self.state()
        if method in ('playback.suspend','playback.resume'):
            if method=='playback.suspend':self.cancel_prefetch(preserve_failure=True)
            if self.loading:self.close(wait=False);return self.state()
            if not self.resource:raise ValueError('media_not_loaded')
            request=urllib.request.Request(self.resource,data=b'suspend' if method.endswith('suspend') else b'resume',method='POST')
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=5) as response:
                if response.status!=204:raise ValueError('media_state_failed')
            self.suspended=method.endswith('suspend')
            return self.state()
        raise ValueError('media_request_failed')

    def cancel_prefetch(self,preserve_failure=False):
        candidate=self.next_media
        self.next_media=None
        if candidate is not None:
            candidate.pump()
            candidate.close(wait=False)
            if preserve_failure and candidate.error:self.next_media=candidate

    def prefetch(self):
        if self.suspended or self.loading or self.error or not self.resource:return self.state()
        available=sorted(n for n in self.metadata.get('episodes',[]) if n>self.metadata['episode'])
        if not available or self.next_media is not None:return self.state()
        candidate=Media(self.account)
        candidate.resolver=self.resolver
        candidate.open(dict(series=self.metadata['series'],episode=available[0],quality=self.arguments.get('quality','720p'),origin=self.arguments['origin']),browser=True,warmup=True)
        self.next_media=candidate
        return self.state()

    def open(self,args,browser=False,warmup=False):
        if browser:
            origin=args.get('origin')
            if not isinstance(origin,str) or len(origin)>2048:raise ValueError('media_request_failed')
            parsed=urllib.parse.urlsplit(origin)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or origin!=f'{parsed.scheme}://{parsed.netloc}':raise ValueError('media_request_failed')
        elif not isinstance(args.get('pipe'),str) or not re.fullmatch(r'\\\\\.\\pipe\\lazybuddy-media-[a-f0-9]{16,64}',args['pipe']):raise ValueError('invalid_media_pipe')
        if os.environ.get('LAZYBUDDY_INSTANCE','default')!='default' and os.environ.get('LAZYBUDDY_PLAYER_REAL')!='1':raise ValueError('media_network_disabled')
        if self.account.probe.state in ('pending','scanned'):raise ValueError('login_required')
        if self.account.probe.state!='signed_in' or not self.account.probe.saved:self.account.restore_local()
        if self.account.probe.state!='signed_in' or not self.account.probe.saved:raise ValueError('login_required')
        series,episode,quality=args.get('series'),args.get('episode'),args.get('quality','720p')
        if not isinstance(series,str) or not series.isascii() or not series.isdecimal() or not 1<=len(series)<=32 or int(series)==0:raise ValueError('invalid_series')
        if type(episode) is not int or not 1<=episode<=9999:raise ValueError('invalid_episode')
        if quality not in ('360p','480p','720p','1080p'):raise ValueError('invalid_quality')
        for option,(minimum,maximum) in {'position':(0,86400),'volume':(0,1),'speed':(0.25,4)}.items():
            if option in args and (type(args[option]) not in (int,float) or not math.isfinite(args[option]) or not minimum<=args[option]<=maximum):raise ValueError('media_request_failed')
        if 'mute' in args and type(args['mute']) is not bool:raise ValueError('media_request_failed')
        args=dict(args,quality=quality)
        candidate=self.next_media
        self.next_media=None
        if candidate is not None:
            candidate.pump()
            if browser and all(candidate.arguments.get(key)==args.get(key) for key in ('series','episode','quality','origin')):
                if not self.account.current_identity((candidate.resolver or {}).get('owner')):
                    candidate.close(wait=False);raise ValueError('saved_session_verification_failed')
                self.close(wait=False)
                # Move only the prepared pipeline; progress writers remain owned by this instance.
                for key in ('generation','events','input_job','input_process','input_reader','metadata','arguments','resolver','loading','error','diagnostic','browser','resource','suspended'):
                    setattr(self,key,getattr(candidate,key))
                self.recorded=self.browser_final=None
                return self.state()
            candidate.close(wait=False)
        self.browser=browser
        self.close(wait=False)
        self.browser=browser;self.suspended=False
        if self.metadata.get('series')!=series:self.metadata={}
        self.metadata.update(series=series,episode=episode)
        self.arguments=args.copy()
        self.error=None;self.diagnostic=None;self.loading=True
        wire=(json.dumps(dict(series=series,episode=episode,quality=quality,resolver=self.resolver,**({'origin':origin,'warmup':warmup} if browser else {})),separators=(',',':'))+'\n').encode()
        if len(wire)>65536:self.loading=False;raise ValueError('resolver_session_too_large')
        try:
            self.input_job=Job()
            self.input_process=self.input_job.spawn([sys.executable,'-I','-B',str(Path(__file__).resolve().parent/'backend/input.py')])
            self.input_process.stdin.write(wire);self.input_process.stdin.flush()
        except Exception:
            self.loading=False;self.stop_resources();raise
        generation=self.generation
        output=self.input_process.stdout
        events=self.events
        def read():
            try:
                while line:=output.readline(65537):
                    if len(line)>65536:raise ValueError('media_input_failed')
                    value=json.loads(line)
                    if not isinstance(value,dict):raise ValueError('media_input_failed')
                    events.put((generation,value))
                    if value.get('ok') is not True:return
            except Exception:pass
            events.put((generation,dict(ok=False,error='media_input_failed')))
        self.input_reader=threading.Thread(target=read,daemon=True)
        self.input_reader.start()
        return self.state()

    def pump(self):
        while True:
            try:generation,result=self.events.get_nowait()
            except queue.Empty:return
            if generation!=self.generation:continue
            if result.get('ok') is not True:
                self.error=code(ValueError(result.get('error')))
                self.diagnostic=result.get('diagnostic')
                self.close(wait=False)
                continue
            try:
                if (not self.loading or result.get('identity_verified') is not True
                        or result.get('series')!=self.metadata['series'] or result.get('episode')!=self.metadata['episode']
                        or not self.account.current_identity(result['resolver']['owner'])):raise ValueError('saved_session_verification_failed')
                self.resolver=result['resolver']
                self.metadata={key:result[key] for key in ('series','episode','episodes','width','height','available_qualities')}
                if self.browser:
                    address=urllib.parse.urlsplit(result['media'])
                    if address.scheme!='http' or address.hostname!='127.0.0.1' or not address.port or address.username or address.password or address.query or address.fragment or not re.fullmatch(r'/[A-Za-z0-9_-]{16,128}/stream\.mp4',address.path):raise ValueError('media_input_failed')
                    self.resource=result['media'];self.loading=False
                    continue
                runtime=Path(os.environ['LAZYBUDDY_DEPENDENCY_MEDIA_RUNTIME_DIR'])
                self.decoder_job=Job()
                self.process=self.decoder_job.spawn([sys.executable,'-I','-B',str(runtime/'service/lazybuddy_media.py')],
                    env=dict(os.environ,LAZYBUDDY_GSTREAMER_DIR=str(runtime/'runtime')))
                output=self.process.stdout;replies=self.replies
                def read():
                    try:
                        while line:=output.readline(65537):
                            if len(line)>65536:raise ValueError('media_runtime_unavailable')
                            replies.put_nowait(json.loads(line))
                    except Exception:pass
                    try:replies.put_nowait(dict(ok=False,error=dict(code='media_runtime_unavailable')))
                    except queue.Full:pass
                self.decoder_reader=threading.Thread(target=read,daemon=True);self.decoder_reader.start()
                self.request('open',dict(uri=result['media'],pipe=self.arguments['pipe']))
                self.loading=False
                for method in ('volume','mute','speed'):
                    if method in self.arguments:self.request(method,dict(value=self.arguments[method]))
                if self.arguments.get('position',0)>0:self.request('seek',dict(value=self.arguments['position']))
                if self.pending_play:self.request('play',{})
            except Exception as error:
                self.error=code(error);self.close(wait=False)

    def state(self):
        if self.browser:return dict(self.metadata,loading=self.loading,prepared=self.resource is not None,session=self.generation,
                resource=dict(url=self.resource,mime='video/mp4') if self.resource else None,suspended=self.suspended,error=self.error,diagnostic=self.diagnostic,
                progress_error=self.local_error or self.account.sync_error,progress_pending=self.flush_thread is not None)
        try:
            state=self.request('status',{}) if self.process is not None else dict(loaded=False,playing=False,eos=False,position=0,duration=0)
        except Exception as failure:
            self.error=code(failure);self.loading=False;self.stop_resources()
            state=dict(loaded=False,playing=False,eos=False,position=0,duration=0)
        if state.get('error'):
            self.error='media_runtime_unavailable';self.loading=False
            self.checkpoint(state);self.stop_resources();self.flush()
            state=dict(state,loaded=False,playing=False)
        return dict(self.metadata,**state)|dict(loading=self.loading,error=self.error or state.get('error'),
                    producer_pid=self.process.pid if self.process else None,progress_error=self.local_error or self.account.sync_error,
                    progress_pending=self.flush_thread is not None)

    def request(self,method,args):
        self.process.stdin.write((json.dumps(dict(version=1,id='media',method=method,args=args))+'\n').encode());self.process.stdin.flush()
        try:reply=self.replies.get(timeout=15)
        except queue.Empty:
            self.decoder_job.stop();raise ValueError('media_runtime_unavailable') from None
        if not isinstance(reply,dict) or reply.get('version')!=1 or reply.get('id')!='media':raise ValueError('media_runtime_unavailable')
        if not reply.get('ok'):raise ValueError(code(ValueError(reply.get('error',{}).get('code'))))
        return reply['data']

    def checkpoint(self,state):
        self.last_saved=time.monotonic()
        try:self.record(state);self.local_error=None
        except Exception:self.local_error='progress_save_failed'

    def record(self,state):
        if not self.metadata or not self.resolver or not state.get('duration') or state.get('position',0)<=0:return
        episode=self.metadata['episode'];checkpoint=(self.metadata['series'],episode,state['position'])
        if self.recorded and checkpoint[:2]==self.recorded[:2] and abs(checkpoint[2]-self.recorded[2])<0.001:return
        catalog=self.resolver['catalog']
        item=next((row['id'] for row in catalog if row['number']==episode and row['playable']),None)
        if item is None:return
        reply=self.account.call(dict(command='progress',series=self.metadata['series'],
            value=dict(episode=episode,time=state['position'],updated=time.time()),
            context=dict(item=item,count=max(row['number'] for row in catalog),duration=state['duration'])))
        if reply.get('error') in ('history_save_failed','history_invalid'):raise ValueError('progress_save_failed')
        self.recorded=checkpoint

    def flush(self):
        if not self.account.pending_progress():return None
        with self.flush_guard:
            if self.flush_thread is not None:self.flush_again=True;return self.flush_thread
            def work():
                while True:
                    try:self.account.call(dict(command='sync',flush=True))
                    except Exception:self.local_error='progress_sync_failed'
                    with self.flush_guard:
                        if not self.flush_again:self.flush_thread=None;return
                        self.flush_again=False
            thread=threading.Thread(target=work,daemon=True)
            self.flush_thread=thread;thread.start()
            return thread

    def close(self,wait=True):
        self.cancel_prefetch()
        self.loading=False;self.pending_play=False
        if self.process:
            try:
                if self.request('status',{}).get('loaded'):self.checkpoint(self.request('pause',{}))
            except Exception:pass
        self.stop_resources()
        if self.browser:
            thread=self.flush() if self.recorded!=self.browser_final else None
            self.browser_final=self.recorded
        else:thread=self.flush()
        with self.flush_guard:thread=self.flush_thread or thread
        if wait and thread:thread.join()
        return thread

    def stop_resources(self):
        self.generation+=1
        self.resource=None
        for prefix in ('decoder','input'):
            job=getattr(self,prefix+'_job')
            process=self.process if prefix=='decoder' else self.input_process
            reader=getattr(self,prefix+'_reader')
            if job:job.stop()
            if process:process.wait(timeout=5)
            if reader:reader.join(timeout=5)
            if process:process.stdin.close();process.stdout.close()
            if job:job.close()
            setattr(self,prefix+'_job',None);setattr(self,prefix+'_reader',None)
        self.process=self.input_process=None
        self.replies=queue.Queue(maxsize=1)
