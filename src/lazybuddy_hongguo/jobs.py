"""Own each helper subtree, including when this service runs without the desktop host."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import time


class Basic(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',wintypes.DWORD),
        ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('processes',wintypes.DWORD),
        ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
class Counters(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ['read_operations','write_operations','other_operations','read_bytes','write_bytes','other_bytes']]
class Limits(ctypes.Structure):
    _fields_=[('basic',Basic),('io',Counters),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
              ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]


class Job:
    def __init__(self,memory_limit=None):
        self.handle=None
        if os.name!='nt' or ctypes.sizeof(Limits)!=144:raise ValueError('unsupported_helper_platform')
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype=wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Limits();limits.basic.flags=0x2000
        if memory_limit:limits.basic.flags|=0x100;limits.process_memory=memory_limit
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close();raise ValueError('helper_job_setup_failed')

    def spawn(self,arguments,**options):
        # Helpers wait for stdin before spawning descendants; attach before sending input.
        process=subprocess.Popen(arguments,stdin=subprocess.PIPE,stdout=options.pop('stdout',subprocess.PIPE),stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,**options)
        if not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
            process.kill();process.wait();process.stdin.close();process.stdout.close()
            raise ValueError('helper_job_assignment_failed')
        return process

    def stop(self):
        if self.handle:self.kernel.TerminateJobObject(self.handle,1)
    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def __del__(self):self.close()


def run(arguments,input,timeout,memory_limit=None,cancelled=None,**options):
    with Job(memory_limit) as job:
        if cancelled is not None and cancelled.is_set():raise ValueError('work_cancelled')
        process=job.spawn(arguments,**options)
        try:
            if cancelled is None:
                stdout,_=process.communicate(input,timeout=timeout)
            else:
                deadline=time.monotonic()+timeout
                while True:
                    if cancelled.is_set():raise ValueError('work_cancelled')
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise subprocess.TimeoutExpired(arguments,timeout)
                    try:
                        stdout,_=process.communicate(input,timeout=min(remaining,.1))
                        break
                    except subprocess.TimeoutExpired:input=None
            return subprocess.CompletedProcess(arguments,process.returncode,stdout)
        except BaseException:
            job.stop();process.wait(timeout=5)
            raise
