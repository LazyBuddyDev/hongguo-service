"""A bounded localhost Range fixture shared by media integration checks."""
import http.server
from pathlib import Path
import re


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path not in ('/fixture.avi','/fixture.mp4'):
            self.send_error(404)
            return
        path = Path(self.directory) / self.path.removeprefix('/')
        size = path.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get('Range')
        if header:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', header)
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else end, end)
            if start > end:
                self.send_error(416)
                return
        self.send_response(206 if header else 200)
        self.send_header('Content-Type', 'video/mp4' if self.path.endswith('.mp4') else 'video/x-msvideo')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if header:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start)
            try:
                self.wfile.write(source.read(end - start + 1))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

