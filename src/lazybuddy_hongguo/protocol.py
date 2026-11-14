"""Versioned public account API; excludes backend session and device material."""
VERSION = 1
import threading
import queue
import base64


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

    def close(self):
        flush=None
        if self.media is not None:
            flush=self.media.close(wait=False)
            self.media=None
        if self.operation is not None:
            self.operation[0].join()
            self.operation = None
        if flush is not None:flush.join()
        if self.account is not None:
            self.account.probe.cancel()
            self.account = None
        self.covers.clear();self.last_account.clear()

    def handle(self, request):
        supplied_id=request.get('id','') if isinstance(request,dict) else ''
        identifier=supplied_id if isinstance(supplied_id,str) and len(supplied_id)<=128 else ''

        def error(code):
            return dict(version=VERSION, id=identifier, ok=False, error=dict(code=code))

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
        if method == 'health':
            return dict(version=VERSION, id=identifier, ok=True, data=dict(service='hongguo', api_version=VERSION))
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
                reply = self.search_factory(request)
                if reply.get('ok'):
                    for row in reply['data']['items']:
                        cover=row.pop('_cover',None)
                        row['has_cover']=bool(cover)
                        if cover:self.covers[row['id']]=cover
                    if len(self.covers)>500:self.covers={row['id']:self.covers[row['id']] for row in reply['data']['items'] if row['id'] in self.covers}
                return reply
            except Exception:
                return error('search_failed')
        if method == 'cover.read':
            if set(args)!={'series'} or not isinstance(args['series'],str) or args['series'] not in self.covers:
                return error('cover_unavailable')
            try:
                from .covers import read
                return dict(version=VERSION,id=identifier,ok=True,data=dict(series=args['series'],**read(self.covers[args['series']])))
            except Exception:
                return error('cover_unavailable')
        commands = {'account.status': 'status', 'account.restore': 'restore', 'account.login': 'login',
                    'account.cancel': 'cancel', 'account.logout': 'logout', 'favorites.read': 'favorites',
                    'favorites.set': 'favorite_set', 'progress.read': 'status', 'progress.sync': 'sync'}
        media_commands = {'media.open': {'series', 'episode', 'quality', 'pipe','position','volume','mute','speed'}, 'media.play': set(),
            'media.pause': set(), 'media.seek': {'value'}, 'media.speed': {'value'}, 'media.boost':{'value'}, 'media.volume': {'value'},
            'media.mute': {'value'}, 'media.status': set(), 'media.close': set()}
        if method in media_commands:
            if set(args) - media_commands[method]:
                return error('invalid_request')
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
            if method in ('account.logout', 'account.login', 'account.restore') and self.media is not None:
                self.media.close()
                self.media = None
            if self.account is None:
                self.account = self.account_factory()
            if method == 'progress.sync' and self.media is not None:
                media=self.media.call('media.status', {})
                if media.get('playing') or media.get('loading'):return error('player_busy')
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
            for row in raw.get('favorites',[]):
                if row.get('cover'):self.covers[row['id']]=row['cover']
            # Explicit projection: never publish owner, playback_session, profile, cookies or signed URLs.
            data = {key: raw.get(key) for key in ('state', 'name', 'error', 'favorites_error')}
            data['qr_png']=base64.b64encode(bytes(raw.get('qr') or b'')).decode('ascii')
            data['operation']=raw.get('operation')
            data['operation_method']=raw.get('operation_method')
            data['favorites'] = [{key: row.get(key) for key in ('id', 'title', 'episodes')}
                                 for row in raw.get('favorites', [])]
            for row,original in zip(data['favorites'],raw.get('favorites',[])):row['has_cover']=bool(original.get('cover'))
            if method.startswith('progress.') or raw.get('operation_method')=='progress.sync':
                data['history'] = {series:{key:row.get(key) for key in ('episode','time','updated')}
                                   for series,row in raw.get('history', {}).items()}
                data.update({key:raw.get(key) for key in ('sync_state','sync_error')})
            return dict(version=VERSION, id=identifier, ok=True, data=data)
        except Exception:
            return error('account_request_failed')
