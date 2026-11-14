"""Measure real PCM output from the production player's scaletempo chain."""
import functools
import http.server
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from toolchain_paths import GSTREAMER as GST


from media_fixture import QuietHandler as Handler


with tempfile.TemporaryDirectory(prefix='qa-media-audio-',dir=ROOT/'target') as temporary:
    directory=Path(temporary)
    environment=dict(os.environ,GST_PLUGIN_PATH=str(GST/'lib/gstreamer-1.0'),
        GST_PLUGIN_SYSTEM_PATH=str(GST/'lib/gstreamer-1.0'),GST_REGISTRY=str(directory/'registry.bin'),
        LAZYBUDDY_GSTREAMER_DIR=str(GST))
    fixture=directory/'fixture.mp4'
    subprocess.run([str(GST/'bin/gst-launch-1.0.exe'),'-q','qtmux','name=mux','!',
        'filesink',f'location={fixture.as_posix()}',
        'videotestsrc','num-buffers=240','pattern=red','!','video/x-raw,width=160,height=90,framerate=30/1',
        '!','jpegenc','!','queue','!','mux.',
        'audiotestsrc','num-buffers=800','samplesperbuffer=480','freq=440','!',
        'audio/x-raw,rate=48000,channels=1,format=S16LE','!',*(['audioconvert','!','avenc_aac','!','aacparse','!'] if '--aac' in sys.argv else []),'queue','!','mux.'],
        env=environment,check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(directory)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    runner=directory/'capture.py'
    runner.write_text('''import ctypes,importlib.util,json,sys,time,os,wave
from pathlib import Path
spec=importlib.util.spec_from_file_location('player',sys.argv[1]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
runtime=module.Gst(os.environ['LAZYBUDDY_GSTREAMER_DIR'])
runtime.function('gst_debug_set_threshold_for_name',None,[ctypes.c_char_p,ctypes.c_int])
runtime.gst.gst_debug_set_threshold_for_name(b'scaletempo',5)
runtime.gst.gst_debug_set_threshold_for_name(b'avidemux',5)
make_bin=runtime.bin
capture=None
def audio_capture(description):
    global capture
    if description.endswith('! autoaudiosink'):
        description=description.replace('scaletempo','scaletempo name=tempo').removesuffix('! autoaudiosink')+'! audioconvert ! audio/x-raw,format=S16LE,channels=1,rate=48000 ! appsink name=capture sync=true max-buffers=8'
        sink=make_bin(description)
        capture=runtime.gst.gst_bin_get_by_name(sink,b'capture')
        return sink
    return make_bin(description)
runtime.bin=audio_capture
player=module.Player(runtime)
app=ctypes.CDLL(str(Path(os.environ['LAZYBUDDY_GSTREAMER_DIR'])/'bin/gstapp-1.0-0.dll'))
app.gst_app_sink_try_pull_sample.argtypes=[ctypes.c_void_p,ctypes.c_uint64];app.gst_app_sink_try_pull_sample.restype=ctypes.c_void_p
runtime.function('gst_sample_get_buffer',ctypes.c_void_p,[ctypes.c_void_p])
runtime.function('gst_buffer_get_size',ctypes.c_size_t,[ctypes.c_void_p])
runtime.function('gst_buffer_extract',ctypes.c_size_t,[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t])
runtime.function('gst_sample_unref',None,[ctypes.c_void_p])
pcm=bytearray()
try:
    player.open(sys.argv[2],sys.argv[4])
    runtime.gst.gst_element_get_state(player.pipeline,None,None,5*module.NS)
    player.command('speed',dict(value=float(sys.argv[5])))
    player.command('play',{})
    began=time.monotonic()
    deadline=time.monotonic()+15
    while True:
        sample=app.gst_app_sink_try_pull_sample(capture,100_000_000)
        if sample:
            buffer=runtime.gst.gst_sample_get_buffer(sample);size=runtime.gst.gst_buffer_get_size(buffer)
            data=ctypes.create_string_buffer(size)
            assert runtime.gst.gst_buffer_extract(buffer,0,data,size)==size
            pcm.extend(data.raw);runtime.gst.gst_sample_unref(sample)
        elif player.state()['eos']:break
        if player.state()['error']:raise RuntimeError('decoder failed: '+str(player.state()['diagnostic']))
        if time.monotonic()>deadline:raise RuntimeError('EOS timeout')
    with wave.open(sys.argv[3],'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(48000);output.writeframes(pcm)
    tempo=runtime.gst.gst_bin_get_by_name(player.pipeline,b'tempo')
    actual=ctypes.c_double()
    runtime.object.g_object_get.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    runtime.object.g_object_get(tempo,b'rate',ctypes.byref(actual),None)
    runtime.gst.gst_object_unref(tempo)
    print(json.dumps(dict(eos=True,rate=player.state()['speed'],tempo_rate=actual.value,wall=time.monotonic()-began)))
finally:
    player.close()
    if capture:runtime.gst.gst_object_unref(capture)
''',encoding='utf-8')
    evidence=[]
    try:
        for rate in ((2.,) if '--debug' in sys.argv else (1.,1.5,2.)):
            output=directory/f'audio-{rate}.wav'
            pipe=r'\\.\pipe\lazybuddy-media-'+secrets.token_hex(16)
            runtime_environment=dict(environment,GST_REGISTRY=str(directory/'player-registry.bin'))
            if os.environ.get('LAZYBUDDY_MEDIA_PACKAGE'):
                runtime_environment.update(LAZYBUDDY_GSTREAMER_DIR=str(Path(os.environ['LAZYBUDDY_MEDIA_PACKAGE'])/'runtime'),PATH=os.environ['SystemRoot']+'\\System32')
            result=subprocess.run([sys.executable,'-I','-B',str(runner),str(ROOT/'runtimes/media/lazybuddy_media.py'),
                f'http://127.0.0.1:{server.server_port}/fixture.mp4',str(output),pipe,str(rate)],
                env=runtime_environment,capture_output=True,encoding='utf-8',errors='replace',timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError('audio fixture failed: '+result.stderr[-1500:])
            print(result.stdout,flush=True)
            if '--debug' in sys.argv:print('\n'.join(line for line in result.stderr.splitlines() if any(word in line.lower() for word in ('seek','segment','scaletempo')))[-10000:],flush=True)
            with wave.open(str(output),'rb') as audio:
                assert audio.getsampwidth()==2 and audio.getnchannels()==1
                sample_rate=audio.getframerate();count=audio.getnframes()
                samples=struct.unpack('<'+'h'*count,audio.readframes(count))
            duration=count/sample_rate
            # Ignore transition edges; upward zero crossings measure the audible fundamental.
            center=samples[sample_rate//2:-sample_rate//2]
            crossings=sum(first<=0<second for first,second in zip(center,center[1:]))
            frequency=crossings/(len(center)/sample_rate)
            print(json.dumps(dict(rate=rate,pcm_duration=duration,frequency=frequency)),flush=True)
            assert abs(duration-8/rate)<0.3,(rate,duration)
            assert abs(frequency-440)<5,(rate,frequency)
            evidence.append(dict(rate=rate,pcm_duration=round(duration,3),frequency=round(frequency,2)))
        print(json.dumps(dict(measured_audio=evidence,audio_codec="aac" if "--aac" in sys.argv else "pcm",pitch_preserved=True,real_account=False,audio_device_used=False)))
    finally:
        server.shutdown();server.server_close();thread.join(5)
