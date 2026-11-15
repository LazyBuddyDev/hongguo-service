"""Saved website identity plus App media resolution, private pipes only."""
import json,os,pathlib,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from . import credentials
from .progressive import Source,Server

def resolve(series,episode,quality,session,passport,on_error=None,origin=None):
    if not isinstance(series,str) or not series.isascii() or not series.isdecimal() or not 1<=len(series)<=32 or int(series)==0:raise ValueError('invalid_series')
    if not isinstance(episode,int) or isinstance(episode,bool) or not 1<=episode<=9999:raise ValueError('invalid_episode')
    if quality not in ('360p','480p','720p','1080p'):raise ValueError('invalid_quality')
    prepare_started=time.monotonic()
    saved=credentials.read()
    if saved is None:raise ValueError('saved_credentials_missing')
    account=passport.restore(saved)
    identity_started=time.monotonic()
    if account.confirm('')!=saved['uid']:raise ValueError('saved_session_verification_failed')
    identity_before_ms=round((time.monotonic()-identity_started)*1000)
    session=session if isinstance(session,dict) and session.get('owner')==saved['uid'] else {}
    profile=session.get('profile') or credentials.read_device(saved['uid'])
    if profile is not None:credentials.remember_device(saved['uid'],profile)
    helper=pathlib.Path(os.environ.get('LAZYBUDDY_HONGGUO_HELPER') or str(pathlib.Path(__file__).resolve().parents[1]/'runtime/hongguo-app-resolver.exe'))
    if not helper.is_file():raise ValueError('app_resolver_unavailable')
    request=dict(series=series,episode=episode,quality=quality,cookies=saved['cookies'],profile=profile,catalog=session.get('catalog',[]) if session.get('series')==series else [])
    wire=(json.dumps(request,separators=(',',':'))+'\n').encode()
    if len(wire)>65536:raise ValueError('resolver_session_too_large')
    began=time.monotonic()
    try:process=subprocess.run([str(helper)],input=wire,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:raise ValueError('app_source_timeout') from None
    if len(process.stdout)>65536:raise ValueError('app_response_invalid')
    value=json.loads(process.stdout)
    if process.returncode or value.get('ok') is not True:
        code=value.get('error')
        diagnostic=value.get('diagnostic')
        if code=='app_playback_unavailable' and isinstance(diagnostic,dict) and diagnostic.get('stage')=='playback' and diagnostic.get('http_status')==200 and diagnostic.get('body_bytes')==0:
            code='app_source_network_error' if diagnostic.get('body_read_ok') is False else 'app_playback_empty_response'
            from lazybuddy_hongguo.diagnostics import describe
            detail=describe(code,stage='playback',context=dict(series=series,episode=episode,quality=quality),status=200,body_bytes=0,body_read_ok=diagnostic.get('body_read_ok'),response_meta=diagnostic.get('response_meta'))
            failure=ValueError(code);failure.diagnostic=detail;raise failure
        if isinstance(diagnostic,dict) and diagnostic.get('stage') in ('playback','catalog','registration'):
            from lazybuddy_hongguo.diagnostics import describe
            detail=describe(code,stage=diagnostic['stage'],context=dict(series=series,episode=episode,quality=quality),status=diagnostic.get('http_status'),body_bytes=diagnostic.get('body_bytes'),body_read_ok=diagnostic.get('body_read_ok'),response_meta=diagnostic.get('response_meta'))
        failure=ValueError(code if code in {'app_access_denied','app_media_unavailable','app_registration_unavailable','app_catalog_unavailable','app_playback_unavailable','app_source_unavailable','episode_unavailable','quality_unavailable','unsupported_wrapped_material','unsupported_media_layout','media_source_rejected','playback_episode_mismatch','app_rate_limited','app_source_network_error'} else 'app_source_unavailable')
        if isinstance(diagnostic,dict) and diagnostic.get('stage') in ('playback','catalog','registration'):failure.diagnostic=detail
        raise failure
    resolve_ms=round((time.monotonic()-began)*1000)
    try:key=bytes.fromhex(value['key']) if value['key'] else None
    except (ValueError,TypeError,KeyError):raise ValueError('unsupported_wrapped_material') from None
    width,height=value.get('width'),value.get('height')
    if any(not isinstance(v,int) or isinstance(v,bool) or not 0<v<=16384 for v in (width,height)):raise ValueError('quality_resolution_not_met')
    def verify_identity():
        started=time.monotonic()
        if account.confirm('')!=saved['uid']:raise ValueError('saved_session_verification_failed')
        return round((time.monotonic()-started)*1000)
    # Independent reads overlap; neither result is handed off until both succeed.
    with ThreadPoolExecutor(max_workers=1) as worker:
        identity=worker.submit(verify_identity)
        source_started=time.monotonic()
        source=Source(value['url'],key,dict(series=series,episode=episode,quality=quality))
        if value.get('size',0)>0 and source.total!=value['size']:raise ValueError('media_size_changed')
        source_prepare_ms=round((time.monotonic()-source_started)*1000)
        identity_after_ms=identity.result()
    credentials.remember_device(saved['uid'],value['profile'])
    catalog=value['catalog']
    episodes=sorted({v['number'] for v in catalog if v['playable']})
    if episode not in episodes:raise ValueError('episode_unavailable')
    server=Server(source,on_error,origin=origin)
    result=dict(ok=True,identity_verified=True,series=series,episode=episode,episodes=episodes,width=width,height=height,available_qualities=value.get('available_qualities',[]),requested_quality=quality,transport='range_mp4',media=server.address,container=dict(video=True,audio=True,protected=False),
        resolver=dict(owner=saved['uid'],series=series,profile=value['profile'],catalog=catalog),
        source_info=dict(backend='app',resolve_ms=resolve_ms,timings=dict(identity_before_ms=identity_before_ms,identity_after_ms=identity_after_ms,source_prepare_ms=source_prepare_ms,total_prepare_ms=round((time.monotonic()-prepare_started)*1000)),device_reused=profile is not None,initial=source.stats()))
    return result,server
