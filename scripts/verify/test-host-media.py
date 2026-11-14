"""Actual host pixels and lifecycle, with a fake account and synthetic local media."""
import functools
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from PIL import Image
from media_fixture import QuietHandler
from windows_fixture import user32,descendants,executable

ROOT=Path(__file__).resolve().parents[2]
HOST_DIR=Path(os.environ['LAZYBUDDY_HOST_DIR']).resolve()
CLI=HOST_DIR/'lazybuddy-cli.exe'
HOST=HOST_DIR/'lazybuddy.exe'
GST=Path(os.environ.get('LAZYBUDDY_SDK_DIR',str(ROOT/'target/native-player-sdk')))/'PFiles64/gstreamer/1.0/msvc_x86_64'
STAGED=Path(os.environ.get('LAZYBUDDY_PACKAGES_DIR',str(ROOT/'target/packages-dev')))
before=user32.GetForegroundWindow()
with tempfile.TemporaryDirectory(prefix='qa-host-media-',dir=ROOT/'target') as temporary:
    directory=Path(temporary)
    environment=dict(os.environ,LAZYBUDDY_INSTANCE='qa-media-'+uuid.uuid4().hex,
        LAZYBUDDY_DATA_DIR=str(directory/'data'),LAZYBUDDY_PLAYER_REAL='1',
        GST_PLUGIN_SYSTEM_PATH_1_0=str(GST/'lib/gstreamer-1.0'),
        GST_PLUGIN_SCANNER_1_0=str(GST/'libexec/gstreamer-1.0/gst-plugin-scanner.exe'),
        GST_REGISTRY=str(directory/'registry.bin'))
    subprocess.run([str(GST/'bin/gst-launch-1.0.exe'),'-q','videotestsrc','pattern=red','num-buffers=900',
        '!','video/x-raw,format=I420,width=320,height=180,framerate=30/1','!','jpegenc','!','qtmux','!',
        'filesink',f'location={json.dumps((directory/"fixture.mp4").as_posix())}'],
        env=environment,check=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=temporary))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    environment.update(PATH=os.environ['SystemRoot']+'\\System32',GST_REGISTRY=str(directory/'host-registry.bin'))
    def cli(*args,required=True):
        result=subprocess.run([str(CLI),*args],env=environment,capture_output=True,encoding='utf-8',errors='replace',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if user32.GetForegroundWindow()!=before:raise RuntimeError('foreground changed')
        if result.returncode:
            if required:raise RuntimeError('CLI failed: '+result.stderr)
            return None
        return json.loads(result.stdout)
    package=directory/'package';service=package/'service';service.mkdir(parents=True)
    shutil.copytree(ROOT/'src/lazybuddy_hongguo',service/'lazybuddy_hongguo',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    manifest=json.loads((ROOT/'module.json').read_text(encoding='utf-8'))
    manifest.update(id='hongguo-fixture',name='合成短剧')
    (package/'module.json').write_text(json.dumps(manifest),encoding='utf-8')
    ready=dict(ok=True,identity_verified=True,series='123',episodes=[1,2],width=640,height=360,available_qualities=[360],
        media=f'http://127.0.0.1:{server.server_port}/fixture.mp4',resolver=dict(owner='fixture',catalog=[dict(id='101',number=1,playable=True),dict(id='102',number=2,playable=True)]))
    (service/'fixture_input.py').write_text('import json,sys\nr=json.loads(sys.stdin.readline())\nv='+repr(ready)+"\nv['episode']=r['episode']\nprint(json.dumps(v),flush=True)\nsys.stdin.read()\n",encoding='utf-8')
    qr=io.BytesIO();Image.new('RGB',(200,200),'white').save(qr,format='PNG')
    (service/'main.py').write_text('''import json,sys,os,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from lazybuddy_hongguo.protocol import Service
from lazybuddy_hongguo.media import Media
from lazybuddy_hongguo.jobs import Job
class Account:
    sync_error=None
    class Probe:
        state='idle';saved=False
        def cancel(self):self.state='cancelled'
    def __init__(self):
        self.probe=self.Probe();self.phase=0
        self.path=Path(os.environ['LAZYBUDDY_DATA_DIR'])/'fake-account.json'
        saved=json.loads(self.path.read_text()) if self.path.exists() else {}
        self.saved=saved.get('saved',False);self.history=saved.get('history',{});self.favorites=[]
    def current_identity(self,owner):return owner=='fixture' and self.probe.state=='signed_in'
    def pending_progress(self):return False
    def call(self,request):
        command=request['command']
        if command=='restore':self.probe.state='signed_in' if self.saved else 'idle';self.probe.saved=self.saved
        if command=='login':self.probe.state='preparing';self.phase=0
        if command=='status' and self.probe.state in ('preparing','pending'):
            self.phase+=1;self.probe.state='pending' if self.phase==1 else 'signed_in'
            if self.phase==2:self.probe.saved=self.saved=True
        if command=='favorite_set':
            time.sleep(2);self.favorites=[dict(id='123',title='合成短剧',episodes=2)] if request['favorite'] else []
        if command=='progress':self.history[request['series']]=request['value']
        if self.saved:self.path.write_text(json.dumps(dict(saved=True,history=self.history)))
        return dict(state=self.probe.state,name='合成账号',qr=QR_FIXTURE if self.probe.state=='pending' else [],history=self.history,favorites=self.favorites,error=None)
original=Job.spawn
def spawn(job,arguments,**options):
    arguments=list(arguments)
    if Path(arguments[-1]).name=='input.py':arguments[-1]=str(Path(__file__).with_name('fixture_input.py'))
    return original(job,arguments,**options)
Job.spawn=spawn
service=Service(Account,media_factory=Media)
try:
    for line in sys.stdin.buffer:
        request=json.loads(line)
        reply=service.handle(request)
        if request['method']=='favorites.set':time.sleep(1.5)
        print(json.dumps(reply),flush=True)
finally:service.close()
'''.replace('QR_FIXTURE',repr(list(qr.getvalue()))),encoding='utf-8')
    # Use the current decoder implementation with the already verified runtime files.
    runtime=directory/'runtime'
    shutil.copytree(Path(os.environ.get('LAZYBUDDY_MEDIA_PACKAGE',str(STAGED/'media-runtime'))),runtime)
    shutil.copyfile(ROOT/'contracts/media-runtime/module.json',runtime/'module.json')
    shutil.copyfile(ROOT/'runtimes/media/lazybuddy_media.py',runtime/'service/lazybuddy_media.py')
    python_runtime=directory/'python-runtime'
    shutil.copytree(STAGED/'python-runtime',python_runtime)
    shutil.copyfile(ROOT/'contracts/python-runtime/module.json',python_runtime/'module.json')
    for path in (python_runtime,runtime,package):cli('modules','install-local',str(path))
    host=subprocess.Popen([str(HOST),'--background'],env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def rpc(command,**args):
            reply=cli('host',json.dumps(dict(version=1,command=command,args=args)))
            if not reply['ok']:raise RuntimeError('host rejected '+command+': '+str(reply))
            return reply.get('data',reply)
        def wait(predicate):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if host.poll() is not None:raise RuntimeError('host exited')
                reply=cli('host',json.dumps(dict(version=1,command='status')),required=False)
                if reply:
                    state=reply['data']
                    if state['error']:raise RuntimeError(json.dumps(dict(error=state['error'],media=state['media'])))
                    if predicate(state):return state
                time.sleep(.05)
            raise RuntimeError('host media state timeout: '+json.dumps(state))
        wait(lambda state:state['hidden'])
        rpc('page.select',id='hongguo-fixture');rpc('window.show')
        wait(lambda state:state['account_state']=='idle' and not state['busy'])
        rpc('account.login')
        pending=wait(lambda state:state['account_state']=='pending' and state['qr_present'])
        wait(lambda state:state['account_state']=='signed_in' and not state['busy'])
        rpc('player.open',series='123',episode=1)
        playing=wait(lambda state:state['media']['playing'] and state['media']['position']>.8)
        assert (playing['media']['width'],playing['media']['height'])==(640,360)
        assert (playing['media']['decoded_width'],playing['media']['decoded_height'])==(320,180)
        rpc('player.speed',value=1.5)
        wait(lambda state:not state['busy'] and state['media']['actual_speed']==1.5)
        rpc('player.boost',value=True)
        accelerated=wait(lambda state:not state['busy'] and state['media']['boosted'])
        assert accelerated['media']['speed']==1.5 and accelerated['media']['actual_speed']==2.
        wait(lambda state:not state['busy'] and state['account_operation']!='pending')
        rpc('player.favorite',value=True)
        wait(lambda state:state['method']=='favorites.set')
        rpc('player.boost',value=False)
        wait(lambda state:not state['busy'] and not state['favorite_pending'] and state['favorite'] and not state['media']['boosted'])
        rpc('player.pause')
        restored=wait(lambda state:not state['busy'] and not state['media']['playing'] and not state['media']['boosted'])
        assert restored['media']['speed']==1.5 and restored['media']['actual_speed']==1.5
        rpc('player.play');playing=wait(lambda state:state['media']['playing'])
        rpc('player.controls',value=True)
        shot=directory/'playing.png';rpc('window.capture',path=str(shot))
        capture=os.environ.get('LAZYBUDDY_QA_CAPTURE')
        if capture:shutil.copyfile(shot,capture)
        with Image.open(shot) as image:
            pixels=memoryview(image.convert('RGB').tobytes())
            red=sum(r>180 and g<80 and b<80 for r,g,b in zip(pixels[0::3],pixels[1::3],pixels[2::3]))
            total=image.width*image.height
        assert red>total*.1,(red,total)
        owned=descendants(host.pid);assert len(owned)==3,{pid:executable(pid) for pid in owned}
        position=playing['media']['position'];rpc('window.hide')
        wait(lambda state:state['hidden']);time.sleep(.8)
        assert descendants(host.pid)==owned
        rpc('window.show');wait(lambda state:not state['hidden'])
        rpc('player.pause')
        paused=wait(lambda state:not state['busy'] and not state['media']['playing'])
        assert paused['media']['position']<position+.5,(position,paused['media']['position'])
        rpc('settings.open',category='about')
        wait(lambda state:not state['service_active'])
        deadline=time.monotonic()+8
        while descendants(host.pid) and time.monotonic()<deadline:time.sleep(.05)
        assert not descendants(host.pid)
        rpc('settings.back')
        wait(lambda state:state['service_active'] and not state['busy'])
        assert len(descendants(host.pid))==1
        rpc('player.play')
        resumed=wait(lambda state:state['media']['playing'])
        assert resumed['media']['position']>=position-.3
        rpc('app.quit');host.wait(15)
        assert host.returncode==0 and not descendants(host.pid)
        print(json.dumps(dict(actual_host_video_pixels=True,red_pixels=red,hidden_keeps_paused_helpers=True,
            hidden_position_stable=True,settings_releases_helpers=True,explicit_resume=True,owned_processes_stopped=True,
            preparing_to_qr_to_signed_in=True,temporary_rate_restored=True,queued_favorite_confirmed=True,foreground_unchanged=True,real_account=False)))
    finally:
        if host.poll() is None:
            remaining=descendants(host.pid);host.terminate();host.wait(5)
            deadline=time.monotonic()+5
            while any(executable(pid) for pid in remaining) and time.monotonic()<deadline:time.sleep(.05)
        server.shutdown();server.server_close();thread.join(5)
