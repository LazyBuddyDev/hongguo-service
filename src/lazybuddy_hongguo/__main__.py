import json
from pathlib import Path
import sys
import subprocess
from .protocol import Service
from .media import Media


def backend():
    from .backend.account import Account
    return Account()


def main():
    def search(request):
        helper = Path(__file__).resolve().parent / 'runtime/lazybuddy-hongguo-search.exe'
        result = subprocess.run([str(helper),'--private-covers'], input=json.dumps(request).encode(), capture_output=True,
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError('search_failed')
        return json.loads(result.stdout)
    service = Service(backend, search, Media)
    try:
        while line := sys.stdin.buffer.readline(65537):
            if len(line) > 65536:
                print(json.dumps(dict(version=1, id='', ok=False, error=dict(code='request_too_large'))), flush=True)
                break
            try:
                request = json.loads(line)
            except ValueError:
                request = None
            print(json.dumps(service.handle(request), separators=(',', ':')), flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
