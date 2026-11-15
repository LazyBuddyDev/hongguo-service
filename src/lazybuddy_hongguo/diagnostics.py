"""Pure, bounded API diagnostics. No file logging or knowledge of any host."""
import os,urllib.parse,traceback
from datetime import datetime,timezone
from pathlib import Path
from .errors import MEDIA_CODES
SERVICE_CODES={'service_started','invalid_request','unsupported_version','suspend_failed','search_unavailable','search_failed','cover_unavailable','cover_failed','media_unavailable','unknown_method','invalid_favorite','account_request_failed','favorites_unavailable','favorites_sync_failed','progress_sync_failed','credential_save_failed','login_step_failed','saved_session_read_failed'}

def host(url):
    try:
        value=urllib.parse.urlsplit(url or '').hostname
        return value if value and len(value)<=253 else None
    except ValueError:return None

def safe_response_meta(value):
    if not isinstance(value,dict):return {}
    enums={'http_version':{'http/1.0','http/1.1','http/2.0','http/3.0','absent','other'},'content_type':{'application/json','application/x-protobuf','text/html','application/octet-stream','absent','other'},'content_encoding':{'gzip','br','deflate','identity','absent','other'},'transfer_encoding':{'chunked','identity','absent','other'}}
    result={key:item for key,allowed in enums.items() if isinstance(item:=value.get(key),str) and item in allowed}
    for key in ('uncompressed','request_id_present','location_present'):
        if type(value.get(key)) is bool:result[key]=value[key]
    for key,low,high in [('declared_length',-1,2**63-1),('date_delta_seconds',-31536000,31536000)]:
        if type(value.get(key)) is int and low<=value[key]<=high:result[key]=value[key]
    return result

def describe(event,*,stage,context=None,status=None,hop=None,source=None,target=None,mode=None,exception_type=None,browser_code=None,exception=None,body_bytes=None,body_read_ok=None,response_meta=None):
    context=context or {}
    response_meta=safe_response_meta(response_meta)
    series=context.get('series');episode=context.get('episode');quality=context.get('quality')
    row=dict(time_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),pid=os.getpid(),
        event=event if isinstance(event,str) and (event in MEDIA_CODES or event in SERVICE_CODES or event in ('media_redirect','browser_media_error')) else 'media_request_failed',stage=stage,
        series=series if isinstance(series,str) and series.isascii() and series.isdecimal() and len(series)<=32 else None,
        episode=episode if type(episode) is int else None,quality=quality if quality in ('360p','480p','720p','1080p') else None,
        response_meta=response_meta,http_status=status if type(status) is int and 100<=status<=599 else None,body_bytes=body_bytes if type(body_bytes) is int and 0<=body_bytes<=8*1024*1024+1 else None,body_read_ok=body_read_ok if type(body_read_ok) is bool else None,hop=hop,source_host=host(source),target_host=host(target),mode=mode or ('direct' if os.environ.get('NO_PROXY')=='*' else 'system'),exception_type=exception_type or (type(exception).__name__ if exception is not None else None),browser_code=browser_code,level='info' if event in ('media_redirect','service_started') else 'error')
    frames=[] if event=='media_redirect' else (traceback.extract_tb(exception.__traceback__,limit=6) if exception is not None and exception.__traceback__ else traceback.extract_stack(limit=6)[:-1])
    row['stack']=[dict(file=Path(frame.filename).name,function=frame.name,line=frame.lineno) for frame in frames]
    return row

def failure(event,**details):
    error=ValueError(event)
    error.diagnostic=describe(event,**details)
    return error
