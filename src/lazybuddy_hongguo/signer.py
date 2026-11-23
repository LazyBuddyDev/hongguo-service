"""One private, lazy signer per service process; no account data enters its logs."""
import atexit
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from .jobs import Job


class LocalSigner:
    def __init__(self):
        self.lock=threading.Lock()
        self.job=None
        self.process=None
        self.address=None
        self.token=None
        self.workspace=None
        self.closed=False

    def environment(self):
        environment=os.environ.copy()
        if environment.get('LAZYBUDDY_HONGGUO_SIGNER_URL'):
            return environment
        root=environment.get('LAZYBUDDY_DEPENDENCY_HONGGUO_SIGNER_DIR')
        if not root:
            return environment
        with self.lock:
            if self.closed:raise ValueError('app_signer_unavailable')
            if self.process is None or self.process.poll() is not None:
                self._close()
                self._start(Path(root),environment)
            environment['LAZYBUDDY_HONGGUO_SIGNER_URL']=self.address
            environment['LAZYBUDDY_HONGGUO_SIGNER_TOKEN']=self.token
            return environment

    def _start(self,root,environment):
        java=root/'java/bin/java.exe'
        if not java.is_file() or not (root/'lib').is_dir():
            raise ValueError('app_signer_unavailable')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port=listener.getsockname()[1]
        self.address=f'http://127.0.0.1:{port}'
        self.token=secrets.token_urlsafe(32)
        environment=environment.copy()
        environment.update(SIGNER_HOST='127.0.0.1',SIGNER_PORT=str(port),SIGNER_TOKEN=self.token)
        # Ignore ambient JVM flags: the packaged runtime owns its startup options.
        for key in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS'):
            environment.pop(key,None)
        self.job=Job()
        try:
            self.workspace=tempfile.TemporaryDirectory(prefix='hongguo-signer-')
            self.process=self.job.spawn([str(java),'-Xmx256m','-Djava.io.tmpdir='+self.workspace.name,'-cp',str(root/'lib/*'),
                'com.openhongguo.signer.SignerServer'],env=environment,cwd=self.workspace.name,stdout=subprocess.DEVNULL)
            self.process.stdin.close()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if self.process.poll() is not None:break
                try:
                    with opener.open(self.address+'/ready',timeout=1) as response:
                        ready=json.loads(response.read(4097))
                    if ready==dict(service='openhongguo-signer',ready=True):return
                except (OSError,ValueError):pass
                time.sleep(.1)
            raise ValueError('app_signer_unavailable')
        except BaseException:
            self._close()
            raise

    def prepare_input(self,process,wire,events,generation):
        # Startup stays off the protocol thread; the private pipe carries the ephemeral token.
        def write():
            try:
                environment=self.environment()
                request=json.loads(wire)
                request['_signer']={key:environment[key] for key in
                    ('LAZYBUDDY_HONGGUO_SIGNER_URL','LAZYBUDDY_HONGGUO_SIGNER_TOKEN') if key in environment}
                payload=(json.dumps(request,separators=(',',':'))+'\n').encode()
                if len(payload)>65536:raise ValueError('resolver_session_too_large')
                if process.poll() is None:
                    process.stdin.write(payload);process.stdin.flush()
            except Exception:
                events.put((generation,dict(ok=False,error='app_source_unavailable')))
        worker=threading.Thread(target=write,daemon=True)
        worker.start()
        return worker

    def _close(self):
        if self.job:
            self.job.stop()
            self.job.close()
        if self.process:
            self.process.wait(timeout=5)
        if self.workspace:
            self.workspace.cleanup()
            self.workspace=None
        self.job=self.process=None
        self.address=self.token=None

    def close(self):
        with self.lock:
            self.closed=True
            self._close()


local=LocalSigner()
atexit.register(local.close)
