import json
from pathlib import Path
import sys
from .protocol import Service
from .media import Media
from .jobs import run


def backend():
    from .backend.account import Account
    return Account()


def main():
    from .network import configure_helpers
    configure_helpers()
    def search(request,cancelled=None):
        helper = Path(__file__).resolve().parent / 'runtime/lazybuddy-hongguo-search.exe'
        result = run([str(helper),'--private-covers'],input=json.dumps(request).encode(),
                     timeout=15,memory_limit=256*1024*1024,cancelled=cancelled)
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
