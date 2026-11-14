"""Short file transactions and a nonblocking cross-process account sync lease."""
from contextlib import contextmanager
import errno
import msvcrt
import time


@contextmanager
def acquire(path,wait=0.):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as file:
        file.seek(0);locked=False;deadline=time.monotonic()+wait
        try:
            while True:
                try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1);locked=True;break
                except OSError as error:
                    if error.errno not in (errno.EACCES,errno.EDEADLK):raise
                    if time.monotonic()>=deadline:break
                    time.sleep(.01)
            yield locked
        finally:
            if locked:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
