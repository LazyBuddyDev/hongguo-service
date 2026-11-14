"""Private App input process: one bounded handoff, then serve only the fixed media."""
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import sys
import urllib.error

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT.parents[1]),str(ROOT.parents[1]/'packages')]
from lazybuddy_hongguo.errors import code
from lazybuddy_hongguo.diagnostics import record


def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetFileType.argtypes=[ctypes.c_void_p]
    if any(kernel.GetFileType(msvcrt.get_osfhandle(stream.fileno()))!=3 for stream in (sys.stdin,sys.stdout)):return 1
    server=None;request={}
    try:
        if os.environ.get('LAZYBUDDY_INSTANCE','default')!='default' and os.environ.get('LAZYBUDDY_PLAYER_REAL')!='1':raise ValueError('media_network_disabled')
        raw=sys.stdin.buffer.readline(65537)
        if len(raw)>65536:raise ValueError('request_too_large')
        request=json.loads(raw)
        from lazybuddy_hongguo.backend import passport
        from lazybuddy_hongguo.backend.app_input import resolve
        def failure(error):
            record(code(error),stage='stream',context=request,exception=error)
            print(json.dumps(dict(ok=False,error=code(error))),flush=True)
        result,server=resolve(request.get('series'),request.get('episode'),request.get('quality'),request.get('resolver'),passport.Passport,failure,origin=request.get('origin'))
        print(json.dumps(result,separators=(',',':')),flush=True)
        server.serve()
        return 0
    except urllib.error.HTTPError as error:
        reply=dict(ok=False,error='media_access_denied' if error.code in (401,403) else 'media_http_error')
        record(reply['error'],stage='prepare',context=request if isinstance(request,dict) else None,status=error.code,exception=error)
    except (urllib.error.URLError,TimeoutError) as error:
        reply=dict(ok=False,error='media_network_error')
        record(reply['error'],stage='prepare',context=request if isinstance(request,dict) else None,exception=error)
    except Exception as error:
        reply=dict(ok=False,error=code(error))
        record(reply['error'],stage='prepare',context=request if isinstance(request,dict) else None,exception=error)
    finally:
        if server:server.close()
    print(json.dumps(reply),flush=True)
    return 1


if __name__=='__main__':raise SystemExit(main())
