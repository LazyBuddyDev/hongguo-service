"""Synthetic file + localhost fixture tests for the separate media control service."""
import ctypes
import functools
import http.server
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HOST_DIR=Path(os.environ['LAZYBUDDY_HOST_DIR']).resolve()
sys.path.insert(0,str(ROOT/'scripts'))
from toolchain_paths import GSTREAMER as GST


from media_fixture import QuietHandler


with tempfile.TemporaryDirectory(prefix='qa-media-service-', dir=ROOT / 'target') as temporary:
    directory = Path(temporary)
    environment = dict(os.environ, LAZYBUDDY_GSTREAMER_DIR=str(GST),
        PATH=str(GST / 'bin') + ';' + os.environ['PATH'],
        GST_PLUGIN_SYSTEM_PATH_1_0=str(GST / 'lib/gstreamer-1.0'),
        GST_PLUGIN_SCANNER_1_0=str(GST / 'libexec/gstreamer-1.0/gst-plugin-scanner.exe'),
        GST_REGISTRY=str(directory / 'registry.bin'), GST_DEBUG='0')
    codec=sys.argv[sys.argv.index('--codec')+1] if '--codec' in sys.argv else 'jpeg'
    if codec not in ('jpeg','h264','h265'):raise ValueError('unsupported synthetic codec')
    fixture = directory / ('fixture.avi' if codec=='jpeg' else 'fixture.mp4')
    encoder={'jpeg':['jpegenc'],
             'h264':['x264enc','speed-preset=ultrafast','tune=zerolatency','threads=1','key-int-max=30','!','h264parse'],
             'h265':['x265enc','speed-preset=ultrafast','tune=zerolatency','key-int-max=30','option-string=pools=1:frame-threads=1','!','h265parse']}[codec]
    subprocess.run([str(GST / 'bin/gst-launch-1.0.exe'), '-q', 'videotestsrc', 'pattern=red',
        'num-buffers=300', '!', 'video/x-raw,format=I420,width=320,height=180,framerate=30/1',
        '!', *encoder, '!', 'avimux' if codec=='jpeg' else 'qtmux', '!', 'filesink', 'location=' + json.dumps(fixture.as_posix())],
        env=environment, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not fixture.is_file() or not fixture.stat().st_size:raise RuntimeError('synthetic fixture missing')
    decoder=['avidemux','!','jpegdec'] if codec=='jpeg' else ['qtdemux','!',codec+'parse','!','avdec_'+codec]
    reference = directory / 'reference.rgba'
    subprocess.run([str(GST / 'bin/gst-launch-1.0.exe'), '-q', 'filesrc', 'location=' + json.dumps(fixture.as_posix()),
        '!', *decoder, '!', 'videoconvert', '!', 'video/x-raw,format=RGBA,colorimetry=sRGB',
        '!', 'identity', 'eos-after=2', '!', 'filesink', 'location=' + json.dumps(reference.as_posix())],
        env=environment, check=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    with reference.open('rb') as source:
        expected = list(source.read(4))
    print('cpu_reference_rgba=' + json.dumps(expected), flush=True)
    if '--reference-only' in sys.argv:
        raise SystemExit(0)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=temporary))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    packaged='--packaged' in sys.argv
    media_root=Path(os.environ.get('LAZYBUDDY_PACKAGES_DIR',str(ROOT/'target/packages-dev')))/'media-runtime'
    interpreter=str(ROOT/'target/packages-dev/python-runtime/bin/python.exe') if packaged else sys.executable
    program=media_root/'service/lazybuddy_media.py' if packaged else ROOT/'runtimes/media/lazybuddy_media.py'
    runtime=media_root/'runtime' if packaged else GST
    producer_environment=dict(environment,LAZYBUDDY_GSTREAMER_DIR=str(runtime),
        PATH=str(Path(interpreter).parent)+';'+str(Path(os.environ['SystemRoot'])/'System32'),
        GST_REGISTRY=str(directory/'producer-registry.bin'),GST_PLUGIN_SYSTEM_PATH_1_0=str(runtime/'lib/gstreamer-1.0'),GST_PLUGIN_SCANNER_1_0=str(runtime/'libexec/gstreamer-1.0/gst-plugin-scanner.exe'))
    producer = subprocess.Popen([interpreter, '-I', '-B', str(program)],
        env=producer_environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def request(method, **args):
            producer.stdin.write(json.dumps(dict(version=1, id='probe', method=method, args=args)) + '\n')
            producer.stdin.flush()
            reply = json.loads(producer.stdout.readline())
            if not reply['ok']:
                raise RuntimeError('media service rejected ' + method + ': ' + reply['error']['code'])
            return reply['data']

        assert request('health')['service'] == 'media'
        pipe = r'\\.\pipe\lazybuddy-media-' + secrets.token_hex(8)
        request('open', uri=f'http://127.0.0.1:{server.server_port}/{fixture.name}', pipe=pipe)
        request('play')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        deadline = time.monotonic() + 15
        while not kernel.WaitNamedPipeW(pipe, 100):
            if time.monotonic() > deadline:
                raise RuntimeError('media service IPC startup timeout: ' + json.dumps(request('status')))
            time.sleep(0.05)
        result = subprocess.run([str(HOST_DIR/'examples/probe.exe'), pipe, str(producer.pid), ','.join(map(str, expected))],
            capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or result.stdout.count('shared_texture_pixels_verified') != 3:
            raise RuntimeError('decoded shared texture verification failed: ' + result.stderr)
        request('pause')
        deadline = time.monotonic() + 3
        while request('status')['playing']:
            if time.monotonic() > deadline:
                raise RuntimeError('pause did not complete')
            time.sleep(0.05)
        request('seek', value=2.0)
        deadline = time.monotonic() + 3
        while not 1.9 <= request('status')['position'] <= 2.2:
            if time.monotonic() > deadline:
                raise RuntimeError('actual seek position did not reach target')
            time.sleep(0.05)
        request('speed', value=1.5)
        request('volume', value=0.0)
        request('mute', value=True)
        request('seek', value=9.5)
        request('speed', value=4.0)
        request('play')
        deadline = time.monotonic() + 5
        while not request('status')['eos']:
            if time.monotonic() > deadline:
                raise RuntimeError('actual GStreamer EOS was not received: ' + json.dumps(request('status')))
            time.sleep(0.05)
        assert request('close')['loaded'] is False
        print(json.dumps(dict(decoded_texture_frames=3, pause=True, seek_position_verified=True, actual_eos=True, speed_accepted=True,
                              volume_and_mute_accepted=True, closed=True, packaged=packaged, codec=codec, real_account=False, visual_checked=False)))
        if '--broker' in sys.argv:
            sys.path.insert(0,str(ROOT/'src'))
            from lazybuddy_hongguo.media import Media
            from lazybuddy_hongguo.jobs import Job
            class Account:
                sync_error=None
                class probe:
                    state='signed_in'
                    saved=True
                def current_identity(self,owner):return owner=='fixture'
                def pending_progress(self):return False
                def call(self,request):return dict(error=None)
            source_script=directory/'fixture-input.py'
            payload=dict(ok=True,identity_verified=True,series='123',episodes=[1,2],width=320,height=180,
                available_qualities=[360],media=f'http://127.0.0.1:{server.server_port}/{fixture.name}',
                resolver=dict(owner='fixture',catalog=[dict(id='1001',number=1,playable=True),dict(id='1002',number=2,playable=True)]))
            source_script.write_text("import json,sys,time\nr=json.loads(sys.stdin.readline())\nif r['episode']==1:time.sleep(20)\nv="+repr(payload)+"\nv['episode']=r['episode']\nprint(json.dumps(v),flush=True)\nsys.stdin.read()\n",encoding='utf-8')
            original_spawn=Job.spawn
            def spawn(job,arguments,**options):
                arguments=list(arguments)
                if Path(arguments[-1]).name=='input.py':arguments[-1]=str(source_script)
                elif Path(arguments[-1]).name!='lazybuddy_media.py':raise AssertionError('unexpected helper')
                options['env']=dict(options.get('env',os.environ),GST_REGISTRY=str(directory/'broker-registry.bin'))
                return original_spawn(job,arguments,**options)
            with patch.dict(os.environ,LAZYBUDDY_INSTANCE='qa-broker',LAZYBUDDY_PLAYER_REAL='1',LAZYBUDDY_DEPENDENCY_MEDIA_RUNTIME_DIR=str(media_root)),patch.object(Job,'spawn',spawn):
                broker=Media(Account())
                try:
                    broker_pipe=r'\\.\pipe\lazybuddy-media-'+secrets.token_hex(8)
                    started=time.monotonic()
                    assert broker.call('media.open',dict(series='123',episode=1,quality='360p',pipe=broker_pipe))['loading']
                    assert time.monotonic()-started<1
                    old=broker.input_process
                    assert broker.call('media.open',dict(series='123',episode=2,quality='360p',pipe=broker_pipe))['loading']
                    assert old.poll() is not None
                    deadline=time.monotonic()+15
                    while True:
                        state=broker.call('media.status',{})
                        if state.get('error'):raise RuntimeError('broker failed: '+state['error'])
                        if state.get('producer_pid') and state.get('loaded'):break
                        if time.monotonic()>deadline:raise RuntimeError('broker input timeout')
                        time.sleep(0.05)
                    assert state['episode']==2
                    broker.call('media.volume',dict(value=0.0))
                    broker.call('media.mute',dict(value=True))
                    broker.call('media.play',{})
                    result=subprocess.run([str(HOST_DIR/'examples/probe.exe'),broker_pipe,str(state['producer_pid']),','.join(map(str,expected))],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode or result.stdout.count('shared_texture_pixels_verified')!=3:raise RuntimeError('broker shared texture verification failed: '+result.stderr)
                    broker.call('media.pause',{})
                    broker.call('media.seek',dict(value=2.0))
                    assert 1.9<=broker.call('media.status',{})['position']<=2.2
                    input_process,decoder_process=broker.input_process,broker.process
                    broker.close()
                    assert input_process.poll() is not None and decoder_process.poll() is not None
                    print(json.dumps(dict(cancellable_broker_input=True,old_input_stopped=True,selected_episode_preserved=True,
                        decoded_texture_frames=3,seek_position_verified=True,owned_helpers_stopped=True,real_account=False)))
                finally:broker.close()
    finally:
        producer.terminate()
        producer.wait(timeout=5)
        producer.stdin.close()
        producer.stdout.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
