"""Bounded local media diagnostics. Never serialize URLs, headers or exceptions."""
import json,logging,logging.handlers,os,urllib.parse,traceback
from datetime import datetime,timezone
from pathlib import Path
from .errors import MEDIA_CODES
from .backend.lease import acquire
MAX_BYTES=128*1024
SERVICE_CODES={'invalid_request','unsupported_version','suspend_failed','search_unavailable','search_failed','cover_unavailable','cover_failed','media_unavailable','unknown_method','invalid_favorite','account_request_failed','favorites_unavailable','favorites_sync_failed','progress_sync_failed','credential_save_failed','login_step_failed','saved_session_read_failed'}

def host(url):
    try:
        value=urllib.parse.urlsplit(url or '').hostname
        return value if value and len(value)<=253 else None
    except ValueError:return None

def record(event,*,stage,context=None,status=None,hop=None,source=None,target=None,mode=None,exception_type=None,browser_code=None,exception=None):
    context=context or {}
    series=context.get('series');episode=context.get('episode');quality=context.get('quality')
    row=dict(time_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),pid=os.getpid(),
        event=event if isinstance(event,str) and (event in MEDIA_CODES or event in SERVICE_CODES or event in ('media_redirect','browser_media_error')) else 'media_request_failed',stage=stage,
        series=series if isinstance(series,str) and series.isascii() and series.isdecimal() and len(series)<=32 else None,
        episode=episode if type(episode) is int else None,quality=quality if quality in ('360p','480p','720p','1080p') else None,
        http_status=status,hop=hop,source_host=host(source),target_host=host(target),mode=mode or ('direct' if os.environ.get('NO_PROXY')=='*' else 'system'),exception_type=exception_type or (type(exception).__name__ if exception is not None else None),browser_code=browser_code,level='info' if event=='media_redirect' else 'error')
    directory=os.environ.get('LAZYBUDDY_DATA_DIR')
    if not directory:return False
    frames=[] if event=='media_redirect' else (traceback.extract_tb(exception.__traceback__,limit=6) if exception is not None and exception.__traceback__ else traceback.extract_stack(limit=6)[:-1])
    row['stack']=[dict(file=Path(frame.filename).name,function=frame.name,line=frame.lineno) for frame in frames]
    root=Path(directory)/'logs'
    try:
        root.mkdir(parents=True,exist_ok=True)
        with acquire(root/'media.lock',wait=.2) as locked:
            if not locked:return False
            handler=logging.handlers.RotatingFileHandler(root/'media.log',maxBytes=MAX_BYTES,backupCount=2,encoding='utf-8')
            try:handler.emit(logging.LogRecord('media',logging.ERROR,__file__,0,json.dumps(row,ensure_ascii=False),(),None))
            finally:handler.close()
        return True
    except OSError:return False
