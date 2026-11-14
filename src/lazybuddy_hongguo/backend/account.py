"""Product account bridge. Only private pipes carry commands; no credentials leave here."""
import copy, hashlib, json, math, os, pathlib, threading
from . import credentials
from lazybuddy_hongguo.jobs import run as run_helper
from . import passport
from .lease import acquire

def username(client):
    data = client.call('/passport/account/info/v2/')
    return str(data.get('screen_name') or data.get('name') or '红果用户')[:80]

def history_path(uid):
    root = os.environ.get('LAZYBUDDY_DATA_DIR') or str(pathlib.Path(os.environ['LOCALAPPDATA']) / 'LazyBuddy')
    key = hashlib.sha256(('LazyBuddy/history/' + uid).encode()).hexdigest()
    return pathlib.Path(root) / ('hongguo-history-' + key + '.json')

def load_history(uid):
    path = history_path(uid)
    if not path.exists(): return {}
    if path.stat().st_size > 1024 * 1024: raise ValueError('history_invalid')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or any(not k.isascii() or not k.isdecimal() or len(k)>32 or not valid_progress(v) for k,v in data.items()): raise ValueError('history_invalid')
    return data

def valid_progress(v):
    return (isinstance(v, dict) and type(v.get('episode')) is int and 1<=v['episode']<=9999
        and type(v.get('time')) in (float,int) and math.isfinite(v['time']) and 0<=v['time']<=86400
        and type(v.get('updated')) in (int,float) and math.isfinite(v['updated']) and v['updated']>=0)

def parse_favorites(raw):
    if not isinstance(raw,dict) or raw.get('code')!=0: raise ValueError('favorites_rejected')
    data=raw.get('data')
    if not isinstance(data,dict) or 'video_shelf_info' not in data: raise ValueError('favorites_invalid')
    rows=data['video_shelf_info']
    if rows is None: rows=[]
    if not isinstance(rows,list) or len(rows)>5000: raise ValueError('favorites_invalid')
    result=[]; seen=set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('favorites_invalid')
        video=row.get('video_data') or row
        ident=str(video.get('series_id') or row.get('series_id') or row.get('book_id') or '')
        if not ident.isascii() or not ident.isdecimal() or not 1<=len(ident)<=32 or int(ident)==0: raise ValueError('favorites_invalid')
        if ident in seen:continue
        seen.add(ident)
        title=row.get('series_title') or video.get('title') or row.get('book_name') or '未命名短剧'
        cover=row.get('series_cover_url') or video.get('cover') or video.get('cover_url') or video.get('thumb_url') or row.get('thumb_url')
        count=video.get('episode_cnt') or video.get('episode_count') or row.get('episode_cnt')
        count=int(count) if str(count or '').isdecimal() else None
        if not isinstance(title,str) or len(title)>256:raise ValueError('favorites_invalid')
        result.append(dict(id=ident,title=title,introduction='',episodes=count,url='https://hongguoduanju.com/detail?series_id='+ident,cover=cover if isinstance(cover,str) and len(cover)<=2048 else None))
    return result

def progress_rows(raw):
    if not isinstance(raw,dict) or raw.get('code')!=0:raise ValueError('progress_rejected')
    rows=raw.get('video_data')
    if rows is None and isinstance(raw.get('data'),dict):rows=raw['data'].get('video_data')
    if not isinstance(rows,list) or len(rows)>=500:raise ValueError('progress_incomplete')
    result={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('progress_invalid')
        series=str(row.get('series_id') or row.get('book_id') or '')
        item=str(row.get('vid') or '')
        if not all(v.isascii() and v.isdecimal() and 1<=len(v)<=32 and int(v)>0 for v in (series,item)):raise ValueError('progress_invalid')
        stamp=row.get('last_watch_time')
        if type(stamp) not in (int,float):raise ValueError('progress_invalid')
        value=dict(episode=row.get('vid_index'),time=row.get('current_play_time',0)/1000.,
            duration=row.get('current_total_time',0)/1000.,updated=stamp/1000. if stamp>100000000000 else stamp,
            item=item,count=row.get('episode_count'),synced=True)
        if not valid_progress(value) or type(value['count']) is not int or value['count']<value['episode']:raise ValueError('progress_invalid')
        if series not in result or value['updated']>result[series]['updated']:result[series]=value
    return result

def uploadable(value):
    return (valid_progress(value) and isinstance(value.get('item'),str) and value['item'].isascii() and value['item'].isdecimal()
        and 1<=len(value['item'])<=32 and int(value['item'])>0 and type(value.get('count')) is int
        and value['episode']<=value['count']<=9999 and type(value.get('duration')) in (float,int)
        and math.isfinite(value['duration']) and 0<value['duration']<=86400 and value['time']<=value['duration'])

class Account:
    def __init__(self):
        self.history_guard=threading.RLock();self.request_guard=threading.Lock();self.sync_guard=threading.Lock()
        self.probe=passport.Probe(persist=True); self.name=''; self.history={}; self.owner=None; self.profile=None; self.favorites=[]; self.favorites_error=None; self.history_invalid=False; self.sync_state='idle'; self.sync_error=None; self.cloud_count=0
    def snapshot(self):
        p=self.probe
        with p.lock:
            signed=p.state=='signed_in' and p.saved
            if signed and self.owner!=p.uid:
                self.favorites=[]; self.profile=None; self.favorites_error=None
                self.name=username(p.client)
                try:self.history=load_history(p.uid); self.history_invalid=False
                except (ValueError,OSError,json.JSONDecodeError):self.history={}; self.history_invalid=True
                self.owner=p.uid
                self.sync_error=None; self.sync_state='idle'
            if signed and self.history_invalid:p.error='history_invalid'
            return dict(state='signed_in' if signed else ('failed' if p.state=='signed_in' else p.state), name=self.name if signed else '',
                sync_state=self.sync_state,sync_error=self.sync_error,cloud_count=self.cloud_count,qr=p.image if p.state in ('pending','scanned') else b'', history=self.history_copy() if signed else {}, error=p.error, favorites=self.favorites if signed else [],favorites_error=self.favorites_error)
    def history_copy(self):
        with self.history_guard:return copy.deepcopy(self.history)
    def save_history(self):
        with self.history_guard:return self._save_history()
    def _save_history(self):
        if self.history_invalid:return False
        path=history_path(self.probe.uid)
        try:
            with acquire(path.with_suffix('.lock'),wait=.2) as locked:
                if not locked:raise OSError('history_busy')
                merged=self.history_copy()
                for series,value in load_history(self.probe.uid).items():
                    local=merged.get(series)
                    if local is None or value['updated']>local['updated']:merged[series]=value
                    elif value['updated']==local['updated'] and value.get('synced') is True and value.get('item')==local.get('item') and value['episode']==local['episode'] and value['time']==local['time']:merged[series]=value
                temp=path.with_suffix('.tmp')
                try:temp.write_text(json.dumps(merged,separators=(',',':')),encoding='utf-8');os.replace(temp,path)
                finally:temp.unlink(missing_ok=True)
                self.history=merged
            return True
        except (OSError,ValueError):self.probe.error='history_save_failed';return False
    def request(self, mode, **payload):
        with self.request_guard:return self._request(mode,**payload)
    def _request(self, mode, **payload):
        record=credentials.read()
        if record is None or record['uid']!=self.probe.uid or self.probe.client.confirm('')!=self.probe.uid:raise ValueError('identity_changed')
        if self.profile is None:self.profile=credentials.read_device(record['uid'])
        helper=pathlib.Path(os.environ.get('LAZYBUDDY_HONGGUO_HELPER') or str(pathlib.Path(__file__).resolve().parents[1]/'runtime/hongguo-app-resolver.exe'))
        request=dict(mode=mode,cookies=record['cookies'],profile=self.profile,**payload)
        result=run_helper([str(helper)],input=json.dumps(request).encode(),timeout=25,memory_limit=512*1024*1024)
        if len(result.stdout)>2*1024*1024:raise ValueError('account_response_invalid')
        response=json.loads(result.stdout)
        if result.returncode or not response.get('ok'):raise ValueError('account_unavailable')
        if self.probe.client.confirm('')!=self.probe.uid:raise ValueError('identity_changed')
        self.profile=response.get('profile')
        if self.profile is not None:credentials.remember_device(record['uid'],self.profile)
        return response
    def cloud(self, mode, progress=None):
        response=self.request(mode,**({'progress':progress} if progress is not None else {}))
        raw=response.get('progress')
        self.require_success(raw)
        return raw
    @staticmethod
    def require_success(raw):
        if not isinstance(raw,dict) or raw.get('code')!=0 or raw.get('error_code',0)!=0:raise ValueError('account_rejected')
        if isinstance(raw.get('data'),dict) and raw['data'].get('error_code',0)!=0:raise ValueError('account_rejected')
    def read_favorites(self):
        raw=self.request('favorites').get('shelf')
        self.require_success(raw)
        self.favorites=parse_favorites(raw)
    def set_favorite(self, series, add):
        if not isinstance(series,str) or not series.isascii() or not series.isdecimal() or not 1<=len(series)<=32 or int(series)==0 or type(add) is not bool:raise ValueError('invalid_favorite')
        if os.environ.get('LAZYBUDDY_INSTANCE','default')!='default' and os.environ.get('LAZYBUDDY_FAVORITES_REAL')!='1':raise ValueError('favorites_write_disabled')
        self.read_favorites()
        if any(row['id']==series for row in self.favorites)!=add:
            self.require_success(self.request('favorite_set',series=series,favorite=add).get('shelf'))
            self.read_favorites()
            if any(row['id']==series for row in self.favorites)!=add:raise ValueError('favorites_not_confirmed')
    def sync_progress(self):
        with self.sync_guard:
            if self.probe.state!='signed_in' or not self.probe.saved:return
            try:
                with acquire(history_path(self.probe.uid).with_suffix('.sync-lock')) as locked:
                    if locked:return self._sync_progress()
                    self.sync_state='pending'
            except OSError:self.sync_error='progress_sync_failed';self.sync_state='failed'
    def _sync_progress(self):
        if self.history_invalid or self.sync_error or self.probe.state!='signed_in' or not self.probe.saved:return
        owner=self.probe.uid
        initial={series:value['updated'] for series,value in self.history_copy().items() if value.get('synced') is False}
        try:
            remote=progress_rows(self.cloud('progress_read'))
            with self.history_guard:
                if self.probe.uid!=owner or self.probe.state!='signed_in':return
                self.cloud_count=len(remote)
                for series,value in remote.items():
                    local=self.history.get(series)
                    if local is None or value['updated']>local['updated'] or (local.get('synced') is not False and value['updated']>=local['updated']):self.history[series]=value
                    elif local.get('synced') is False and value['item']==local.get('item') and abs(value['time']-local['time'])<1.5 and abs(value['updated']-local['updated'])<1.5:local['synced']=True
                if not self.save_history():return
                pending=[(series,value.copy()) for series,value in self.history.items() if initial.get(series)==value['updated'] and value.get('synced') is False and uploadable(value)]
            writable=os.environ.get('LAZYBUDDY_INSTANCE','default')=='default' or os.environ.get('LAZYBUDDY_PROGRESS_REAL')=='1'
            if pending and not writable:self.sync_state='read_only';return
            for series,value in pending:
                if self.probe.uid!=owner or self.probe.state!='signed_in':return
                wire=dict(series=series,item=value['item'],episode=value['episode'],count=value['count'],time=round(value['time']*1000),duration=round(value['duration']*1000),updated=round(value['updated']*1000))
                self.cloud('progress_upload',wire)
                confirmed=progress_rows(self.cloud('progress_read')).get(series)
                if confirmed is None or confirmed['episode']!=value['episode'] or abs(confirmed['time']-value['time'])>1.5:raise ValueError('progress_not_confirmed')
                with self.history_guard:
                    if self.probe.uid!=owner:return
                    # A newer observed checkpoint stays pending while this upload completes.
                    if self.history.get(series,{}).get('updated')==value['updated']:self.history[series]['synced']=True
                    if not self.save_history():return
            self.sync_state='pending' if any(value.get('synced') is False for value in self.history_copy().values()) else 'synced'
        except Exception:
            self.sync_error='progress_sync_failed';self.sync_state='failed'
    def pending_progress(self):
        with self.history_guard:return not self.history_invalid and any(value.get("synced") is False for value in self.history.values())
    def current_identity(self,owner):
        record=credentials.read()
        return (record is not None and record['uid']==owner and self.probe.uid==owner
                and self.probe.state=='signed_in' and self.probe.saved)
    def restore_local(self):
        self.probe.restore()
        if self.probe.state!='signed_in' or not self.probe.saved:return
        self.owner=self.probe.uid
        try:self.history=load_history(self.owner);self.history_invalid=False
        except (ValueError,OSError,json.JSONDecodeError):self.history={};self.history_invalid=True
        self.profile=credentials.read_device(self.owner)
    def call(self, request):
        command=request.get('command')
        if command=='restore':
            self.owner=None
            self.probe.cancel(); self.probe.saved=False; self.probe.error=None; self.probe.restore()
        elif command=='login':
            self.probe.cancel(); self.probe=passport.Probe(persist=True); self.probe.start()
        elif command=='cancel':
            self.probe.cancel();self.probe.saved=False;self.probe.restore()
        elif command=='logout':
            self.probe.cancel(); credentials.delete(); self.name=''; self.owner=None; self.history={}; self.favorites=[]; self.profile=None; self.favorites_error=None; self.sync_error=None; self.sync_state='idle'
        elif command in ('favorites','favorite_set'):
            if self.probe.state!='signed_in' or not self.probe.saved:raise ValueError('login_required')
            try:
                if command=='favorite_set':self.set_favorite(request.get('series'),request.get('favorite'))
                else:self.read_favorites()
                self.favorites_error=None
            except Exception:
                self.favorites_error='favorites_sync_failed' if command=='favorite_set' else 'favorites_unavailable'
        elif command=='sync':
            if request.get('flush') is not True and not self.history_invalid:self.sync_error=None
            if request.get('flush') is not True or any(value.get('synced') is False for value in self.history_copy().values()):
                self.sync_progress()
        elif command=='progress':
            if self.history_invalid:return self.snapshot()
            if self.probe.state!='signed_in' or not self.probe.saved: raise ValueError('login_required')
            series=request.get('series'); value=request.get('value')
            if not isinstance(series,str) or not series.isascii() or not series.isdecimal() or not 1<=len(series)<=32 or not valid_progress(value): raise ValueError('history_invalid')
            context=request.get('context')
            if isinstance(context,dict):
                candidate=dict(value,**{key:context.get(key) for key in ('item','duration','count')},synced=False)
                if uploadable(candidate):value=candidate
            with self.history_guard:
                self.history[series]=value
                if value.get('synced') is False:self.sync_state='pending'
                self.save_history()
        elif command!='status': raise ValueError('invalid_command')
        return self.snapshot()
