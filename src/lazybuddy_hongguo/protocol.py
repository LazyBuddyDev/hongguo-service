"""Versioned public account API; excludes backend session and device material."""
VERSION = 1
import threading
import queue
import base64
import time
from dataclasses import dataclass

DEFERRED={'search','cover.read','account.restore','account.cancel'}

@dataclass
class Work:
    method:str
    cancelled:threading.Event
    result:queue.Queue
    thread:threading.Thread
    deadline:float


class Service:
    def __init__(self, account_factory, search_factory=None, media_factory=None):
        self.account_factory = account_factory
        self.search_factory = search_factory
        self.account = None
        self.media_factory = media_factory
        self.media = None
        self.covers = {}
        self.last_account = {}
        self.operation = None
        self.work={}
        self.next_work=0

    def close(self, timeout=5.):
        deadline=time.monotonic()+timeout
        self.cancel_work()
        account=self.account
        if account is not None:account.quiesce()
        flush=None
        if self.media is not None:
            flush=self.media.close(wait=False)
            self.media=None
        operation,self.operation=self.operation,None
        if account is not None and account.write_pending:
            for thread in (operation[0] if operation else None,flush):
                if thread is not None:thread.join(max(0.,deadline-time.monotonic()))
        if self.account is not None:
            self.account.probe.cancel()
            self.account = None
        self.covers.clear();self.last_account.clear()

    def cancel_work(self):
        restoring=self.restoring()
        for job in self.work.values():job.cancelled.set()
        if restoring and self.account is not None:
            self.account.quiesce()
            self.account=None
            self.last_account={}
            self.covers.clear()

    def restoring(self):
        return any(job.method.startswith('account.') for job in self.work.values() if not job.cancelled.is_set())

    def expire_work(self):
        now=time.monotonic()
        if any(job.method.startswith('account.') and job.deadline<=now and not job.cancelled.is_set() for job in self.work.values()):
            self.cancel_work()
        for key,job in list(self.work.items()):
            if job.deadline<=now:job.cancelled.set()
            if job.cancelled.is_set() and not job.thread.is_alive():del self.work[key]

    def search_reply(self,reply):
        if reply.get('ok'):
            for row in reply['data']['items']:
                cover=row.pop('_cover',None)
                row['has_cover']=bool(cover)
                if cover:self.covers[row['id']]=cover
            if len(self.covers)>500:self.covers={row['id']:self.covers[row['id']] for row in reply['data']['items'] if row['id'] in self.covers}
        else:
            from .diagnostics import describe
            reply.setdefault('error',{})['diagnostic']=describe('search_failed',stage='search')
        return reply

    def cover_work(self,series):
        from .covers import read,read_cached
        url=self.covers.get(series)
        if url is None:return lambda cancelled:read_cached(series)
        favorite=any(row.get('id')==series for row in self.last_account.get('favorites',[]))
        return lambda cancelled:read(url,series=series if favorite else None,cancelled=cancelled)

    def begin_work(self,request,method,args):
        if len(self.work)>=8 or (method=='search' and any(j.method==method for j in self.work.values())):
            raise ValueError('request_busy')
        if method=='search':
            if self.search_factory is None:raise ValueError('search_unavailable')
            def run(cancelled):return self.search_factory(dict(request,method=method,args=args),cancelled)
        elif method=='cover.read':
            if set(args)!={'series'} or not isinstance(args['series'],str):raise ValueError('cover_unavailable')
            read=self.cover_work(args['series'])
            def run(cancelled):return dict(series=args['series'],**read(cancelled))
        else:
            if args:raise ValueError('invalid_request')
            if self.restoring():raise ValueError('account_busy')
            if self.operation is not None:
                if self.operation[0].is_alive():raise ValueError('account_busy')
                self.operation=None
            if method=='account.restore' and self.media is not None:
                if self.account.write_pending:raise ValueError('account_busy')
                self.account.pause_writes()
                self.media.close(wait=False);self.media=None
                self.account.resume_writes()
            if self.account is None:self.account=self.account_factory()
            account=self.account
            def run(cancelled):return account.call(dict(command=method.split('.')[1],cancelled=cancelled))
        cancelled=threading.Event()
        result=queue.Queue(maxsize=1)
        def execute():
            try:
                if not cancelled.is_set():result.put((True,run(cancelled)))
            except Exception:result.put((False,None))
        thread=threading.Thread(target=execute,daemon=True)
        self.next_work+=1
        self.work[self.next_work]=Work(method,cancelled,result,thread,time.monotonic()+60)
        thread.start()
        return self.next_work

    def account_reply(self,raw,method):
        for row in raw.get('favorites',[]):
            if row.get('cover'):self.covers[row['id']]=row['cover']
        data={key:raw.get(key) for key in ('state','name','error','favorites_error','operation','operation_method')}
        data['qr_png']=base64.b64encode(bytes(raw.get('qr') or b'')).decode('ascii')
        data['favorites']=[{**{key:row.get(key) for key in ('id','title','episodes')},'has_cover':bool(row.get('cover'))} for row in raw.get('favorites',[])]
        if method.startswith('progress.') or raw.get('operation_method')=='progress.sync':
            data['history']={series:{key:row.get(key) for key in ('episode','time','updated')} for series,row in raw.get('history',{}).items()}
            data.update({key:raw.get(key) for key in ('sync_state','sync_error')})
        from .diagnostics import describe
        for field in ('error','favorites_error','sync_error'):
            if data.get(field):data['diagnostic']=describe(data[field],stage='account')
        return data

    def handle(self, request):
        supplied_id=request.get('id','') if isinstance(request,dict) else ''
        identifier=supplied_id if isinstance(supplied_id,str) and len(supplied_id)<=128 else ''

        def error(code,exception=None):
            from .diagnostics import describe
            detail=describe(code,stage='api',context=request.get('args') if isinstance(request,dict) and isinstance(request.get('args'),dict) else None,exception=exception)
            return dict(version=VERSION, id=identifier, ok=False, error=dict(code=code,diagnostic=detail))

        if not isinstance(request, dict) or set(request) - {'version', 'id', 'method', 'args'}:
            return error('invalid_request')
        if type(request.get('version')) is not int or request.get('version') != VERSION:
            return error('unsupported_version')
        if not isinstance(supplied_id, str) or len(supplied_id)>128:
            return error('invalid_request')
        method = request.get('method')
        if not isinstance(method,str) or len(method)>64:return error('invalid_request')
        args = request.get('args', {})
        if not isinstance(args, dict):
            return error('invalid_request')
        def ok(data):return dict(version=VERSION,id=identifier,ok=True,data=data)
        self.expire_work()
        if method=='work.cancel':
            if args:return error('invalid_request')
            self.cancel_work()
            return ok({})
        if method=='work.begin':
            if set(args)!={'method','args'} or type(args['method']) is not str or args['method'] not in DEFERRED or not isinstance(args['args'],dict):
                return error('invalid_request')
            try:return ok(dict(job=self.begin_work(request,args['method'],args['args'])))
            except ValueError as failure:return error(str(failure) if str(failure) in ('request_busy','search_unavailable','cover_unavailable','invalid_request','account_busy') else 'account_request_failed')
            except Exception:return error('account_request_failed')
        if method=='work.status':
            if set(args)!={'job'} or type(args['job']) is not int:return error('invalid_request')
            job=self.work.get(args['job'])
            if job is None or job.cancelled.is_set():return error('work_cancelled')
            try:success,payload=job.result.get_nowait()
            except queue.Empty:return ok(dict(pending=True))
            del self.work[args['job']]
            code={'search':'search_failed','cover.read':'cover_unavailable'}.get(job.method,'account_request_failed')
            if not success:return ok(dict(reply=error(code)))
            try:
                if job.method=='search':reply=self.search_reply(payload)
                elif job.method=='cover.read':reply=ok(payload)
                else:self.last_account=payload;reply=ok(self.account_reply(payload,job.method))
                return ok(dict(reply=reply))
            except Exception:return ok(dict(reply=error(code)))
        if method == 'health':
            return dict(version=VERSION, id=identifier, ok=True, data=dict(service='hongguo', api_version=VERSION,capabilities=dict(browser_resources=True,credential_scopes=True)))
        if method=='lifecycle.suspend':
            if args:return error('invalid_request')
            try:
                self.close()
                return dict(version=VERSION,id=identifier,ok=True,data=dict(suspended=True))
            except Exception:
                return error('suspend_failed')
        if method == 'search':
            try:
                if self.search_factory is None:
                    return error('search_unavailable')
                return self.search_reply(self.search_factory(request))
            except Exception:
                return error('search_failed')
        if method == 'cover.read':
            if set(args)!={'series'} or not isinstance(args['series'],str):
                return error('cover_unavailable')
            try:
                series=args['series']
                return ok(dict(series=series,**self.cover_work(series)(None)))
            except Exception:
                return error('cover_unavailable')
        commands = {'account.status': 'status', 'account.restore': 'restore', 'account.login': 'login',
                    'account.cancel': 'cancel', 'account.logout': 'logout', 'favorites.read': 'favorites',
                    'favorites.set': 'favorite_set', 'progress.read': 'status', 'progress.sync': 'sync'}
        media_commands = {'media.open': {'series', 'episode', 'quality', 'pipe','position','volume','mute','speed'}, 'media.play': set(),
            'media.pause': set(), 'media.seek': {'value'}, 'media.speed': {'value'}, 'media.boost':{'value'}, 'media.volume': {'value'},
            'media.mute': {'value'}, 'media.status': set(), 'media.close': set()}
        media_commands.update({'playback.open':{'series','episode','quality','origin','refresh_catalog'},'playback.status':set(),
            'playback.report_error':{'session','code'},
            'playback.prefetch':{'session'},'playback.prefetch_cancel':{'session'},'playback.suspend':{'session'},'playback.resume':{'session'},'playback.close':{'session'},'playback.checkpoint':{'session','position','duration','final'}})
        if method in media_commands:
            if set(args) - media_commands[method]:
                return error('invalid_request')
            if self.restoring() and method in ('media.open','playback.open'):return error('account_busy')
            try:
                if self.media_factory is None:
                    return error('media_unavailable')
                if self.account is None:
                    self.account = self.account_factory()
                if self.media is None:
                    self.media = self.media_factory(self.account)
                data = self.media.call(method, args)
                return dict(version=VERSION, id=identifier, ok=True, data=data)
            except Exception as failure:
                from .errors import code
                return error(code(failure))
        if method not in commands:
            return error('unknown_method')
        allowed = {'series', 'favorite'} if method == 'favorites.set' else set()
        if set(args) - allowed:
            return error('invalid_request')
        if method == 'favorites.set':
            series = args.get('series')
            if (not isinstance(series, str) or not series.isascii() or not series.isdecimal()
                    or not 1 <= len(series) <= 32 or int(series) == 0 or type(args.get('favorite')) is not bool):
                return error('invalid_favorite')
        try:
            if self.restoring():
                if method in ('account.status','progress.read'):
                    return ok(self.account_reply(self.last_account,method))
                return error('account_busy')
            if self.operation is not None:
                thread,replies,operation_method=self.operation
                if thread.is_alive():
                    if method not in ('account.status','progress.read'):return error('account_busy')
                    raw=dict(self.account.call(dict(command='status')) if method=='progress.read' else self.last_account,
                             operation='pending',operation_method=operation_method)
                else:
                    self.last_account=replies.get_nowait()
                    self.operation=None
                    raw=self.last_account
                    if method!='account.status':raw=None
            else:raw=None
            if method in ('account.logout', 'account.login', 'account.restore'):
                if self.media is not None:
                    if self.account.write_pending:return error('account_busy')
                    self.account.pause_writes()
                    self.media.close(wait=False)
                    self.media=None
                    self.account.resume_writes()
                if method!='account.restore':self.cancel_work()
            if self.account is None:
                self.account = self.account_factory()
            if method == 'progress.sync' and self.media is not None:
                media=self.media.call('media.status', {})
                if media.get('playing') or media.get('loading') or media.get('prepared'):return error('player_busy')
            if raw is None:
                if method in ('favorites.read','favorites.set','progress.sync'):
                    if self.last_account.get('state')!='signed_in':return error('login_required')
                    replies=queue.Queue(maxsize=1)
                    account=self.account;previous=self.last_account.copy()
                    def work():
                        try:result=account.call(dict(command=commands[method],**args))
                        except Exception:result=dict(previous,**({'sync_error':'progress_sync_failed','sync_state':'failed'} if method=='progress.sync' else {'favorites_error':'favorites_sync_failed'}))
                        replies.put(dict(result,operation_method=method))
                    thread=threading.Thread(target=work,daemon=True)
                    self.operation=(thread,replies,method);thread.start()
                    raw=dict(self.last_account,operation='pending',operation_method=method)
                else:
                    raw=self.account.call(dict(command=commands[method],**args))
                    self.last_account=raw
            if method in ('account.logout','account.login'):
                self.covers.clear()
            return ok(self.account_reply(raw,method))
        except Exception as exception:
            from .errors import code
            if code(exception)=='invalid_credential_scope':return error('invalid_credential_scope')
            return error('account_request_failed',exception)
