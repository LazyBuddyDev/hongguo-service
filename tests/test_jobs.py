import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from lazybuddy_hongguo.jobs import Job


@unittest.skipUnless(os.name=='nt','Windows helper ownership')
class Jobs(unittest.TestCase):
    def test_stopping_input_job_also_stops_its_descendants(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        root=Path.cwd()/'target'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='qa-job-',dir=root) as temporary:
            program=Path(temporary)/'input.py'
            program.write_text("import json,subprocess,sys,time\nsys.stdin.readline()\nchild=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)\nprint(json.dumps(dict(pid=child.pid)),flush=True)\ntime.sleep(30)\n",encoding='utf-8')
            job=Job()
            process=job.spawn([sys.executable,'-I','-B',str(program)])
            descendant=None
            try:
                process.stdin.write(b'go\n');process.stdin.flush()
                child=json.loads(process.stdout.readline(4096))['pid']
                descendant=kernel.OpenProcess(0x00100000,False,child)
                self.assertTrue(descendant)
                job.stop();process.wait(timeout=3)
                self.assertEqual(kernel.WaitForSingleObject(descendant,3000),0)
            finally:
                job.close()
                if process.poll() is None:process.kill();process.wait()
                process.stdin.close();process.stdout.close()
                if descendant:kernel.CloseHandle(descendant)
