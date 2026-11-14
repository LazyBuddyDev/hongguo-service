"""Bounded, memory-only CENC track preparation for the isolated native prototype."""
import base64
import http.server
import secrets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# shortcut: buffer one bounded episode; add indexed range preparation before supporting longer tracks.
MAX_TRACK_BYTES = 64 * 1024 * 1024


def wrapped_key(material):
    # Port of openhongguo internal/drm/spade.go; attribution and Apache license in licenses/.
    try:
        raw = base64.b64decode(material.strip(), validate=True)
        marker = raw[0] ^ raw[1] ^ raw[2]
        size = marker - 0x30
        length = len(raw) - marker + 0x2f
        if not 1 <= size <= len(raw) - 2 or not 2 <= length < len(raw):
            raise ValueError()
        tail = len(raw) - size
        tag = bytes(raw[tail - 2] ^ raw[tail - 1] ^ b for b in raw[tail:])
        if tag != b'22':
            raise ValueError()
        buf = bytearray(raw[1:1 + length])
        previous, current = 0x55, 0xfa
        for i, b in enumerate(buf):
            # Website access material uses addition; App spade material is not interchangeable.
            buf[i] = (((current if i % 2 == 0 else previous) ^ b) + 0x15 + i.bit_count()) & 255
            if i % 2 == 0:
                current = b
            else:
                previous = b
        version_length = int(chr(buf[0]), 16)
        if not 1 <= version_length < length:
            raise ValueError()
        key = bytes.fromhex(buf[1:length - version_length].decode('ascii'))
        if len(key) != 16:
            raise ValueError()
        return key
    except (ValueError, IndexError, TypeError, UnicodeError):
        raise ValueError('unsupported_wrapped_material') from None


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    while start < end:
        if end - start < 8:
            raise ValueError('invalid_media_box')
        size = int.from_bytes(data[start:start + 4], 'big')
        header = 8
        if size == 1:
            if end - start < 16:
                raise ValueError('invalid_media_box')
            size = int.from_bytes(data[start + 8:start + 16], 'big')
            header = 16
        if size == 0:
            size = end - start
        if size < header or size > end - start:
            raise ValueError('invalid_media_box')
        yield data[start + 4:start + 8], start, start + header, start + size
        start += size


def only(entries, kind):
    found = [b for b in entries if b[0] == kind]
    if len(found) != 1:
        raise ValueError('unsupported_media_layout')
    return found[0]


def uint(data, offset, size, end):
    if offset < 0 or offset + size > end:
        raise ValueError('invalid_media_field')
    return int.from_bytes(data[offset:offset + size], 'big')


def prepare_track(data, key):
    """Keep all byte offsets while preparing CENC v0 / senc fragmented MP4 samples."""
    if not 8 <= len(data) <= MAX_TRACK_BYTES or len(key) != 16:
        raise ValueError('media_limit_exceeded')
    out = bytearray(data)
    top = list(boxes(out))
    moov = only(top, b'moov')
    iv_sizes = []

    def clear_entries(start, end):
        for kind, begin, payload, stop in list(boxes(out, start, end)):
            if kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                clear_entries(payload, stop)
            elif kind == b'pssh':
                out[begin + 4:begin + 8] = b'free'
            elif kind == b'stsd':
                entries = list(boxes(out, payload + 8, stop))
                if uint(out, payload + 4, 4, stop) != len(entries) or not 1 <= len(entries) <= 2:
                    raise ValueError('unsupported_sample_description')
                for typ, e, ep, ee in entries:
                    if typ in (b'avc1', b'hvc1', b'hev1', b'mp4a'):
                        continue
                    if typ not in (b'encv', b'enca'):
                        raise ValueError('unsupported_sample_description')
                    extra = 78 if typ == b'encv' else 28
                    if typ == b'enca' and uint(out, ep + 8, 2, ee) != 0:
                        raise ValueError('unsupported_audio_entry')
                    sinf = only(list(boxes(out, ep + extra, ee)), b'sinf')
                    children = list(boxes(out, sinf[2], sinf[3]))
                    frma = only(children, b'frma')
                    original = bytes(out[frma[2]:frma[3]])
                    if original not in (b'avc1', b'hvc1', b'hev1', b'mp4a'):
                        raise ValueError('unsupported_media_codec')
                    schm = only(children, b'schm')
                    if out[schm[2] + 4:schm[2] + 8] != b'cenc':
                        raise ValueError('unsupported_protection_scheme')
                    schi = only(children, b'schi')
                    tenc = only(list(boxes(out, schi[2], schi[3])), b'tenc')
                    p = tenc[2]
                    if tenc[3] - p != 24 or out[p:p + 7] != b'\0\0\0\0\0\0\1' or out[p + 7] not in (8, 16):
                        raise ValueError('unsupported_track_encryption')
                    iv_sizes.append(out[p + 7])
                    out[e + 4:e + 8] = original
                    out[sinf[1] + 4:sinf[1] + 8] = b'free'

    clear_entries(moov[2], moov[3])
    if len(iv_sizes) != 1:
        raise ValueError('unsupported_track_count')
    iv_size = iv_sizes[0]
    samples = 0
    for kind, begin, payload, end in top:
        if kind != b'moof':
            continue
        traf = only(list(boxes(out, payload, end)), b'traf')
        entries = list(boxes(out, traf[2], traf[3]))
        if any(b[0] in (b'sbgp', b'sgpd') for b in entries):
            raise ValueError('unsupported_sample_encryption_groups')
        tfhd = only(entries, b'tfhd')
        p, limit = tfhd[2], tfhd[3]
        flags = uint(out, p, 4, limit)
        if flags & ~0x02003b:
            raise ValueError('unsupported_fragment_header')
        p += 8
        base = begin
        if flags & 1:
            base = uint(out, p, 8, limit)
            p += 8
        elif not flags & 0x020000:
            raise ValueError('unsupported_fragment_base')
        if flags & 2:
            p += 4
        if flags & 8:
            p += 4
        default_size = uint(out, p, 4, limit) if flags & 16 else 0
        if flags & 16:
            p += 4
        if flags & 32:
            p += 4
        if p != limit:
            raise ValueError('invalid_fragment_header')
        senc = only(entries, b'senc')
        sp, se = senc[2], senc[3]
        sf = uint(out, sp, 4, se)
        if sf not in (0, 2):
            raise ValueError('unsupported_sample_encryption')
        count = uint(out, sp + 4, 4, se)
        sp += 8
        decoded = 0
        previous_end = None
        for _, _, tp, te in [b for b in entries if b[0] == b'trun']:
            flags = uint(out, tp, 4, te)
            if flags & ~0x01000f05:
                raise ValueError('unsupported_sample_run')
            run_count = uint(out, tp + 4, 4, te)
            tp += 8
            if run_count > count - decoded:
                raise ValueError('invalid_sample_count')
            if flags & 1:
                offset = uint(out, tp, 4, te)
                if offset >= 1 << 31:
                    offset -= 1 << 32
                sample = base + offset
                tp += 4
            elif previous_end is not None:
                sample = previous_end
            else:
                raise ValueError('missing_sample_offset')
            if flags & 4:
                tp += 4
            for _ in range(run_count):
                if flags & 0x100:
                    tp += 4
                size = uint(out, tp, 4, te) if flags & 0x200 else default_size
                if flags & 0x200:
                    tp += 4
                if flags & 0x400:
                    tp += 4
                if flags & 0x800:
                    tp += 4
                if size <= 0 or not any(t == b'mdat' and lo <= sample and sample + size <= hi for t, _, lo, hi in top):
                    raise ValueError('sample_outside_media')
                if sp + iv_size > se:
                    raise ValueError('invalid_sample_iv')
                iv = bytes(out[sp:sp + iv_size]) + b'\0' * (16 - iv_size)
                sp += iv_size
                cipher = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
                spans = [(0, size)]
                if sf & 2:
                    n = uint(out, sp, 2, se)
                    sp += 2
                    spans = []
                    for _ in range(n):
                        spans.append((uint(out, sp, 2, se), uint(out, sp + 2, 4, se)))
                        sp += 6
                cursor = sample
                for clear, encrypted in spans:
                    cursor += clear
                    if cursor + encrypted > sample + size:
                        raise ValueError('invalid_sample_subrange')
                    out[cursor:cursor + encrypted] = cipher.update(bytes(out[cursor:cursor + encrypted]))
                    cursor += encrypted
                cipher.finalize()
                if spans and cursor != sample + size:
                    raise ValueError('invalid_sample_subrange')
                sample += size
                decoded += 1
            if tp != te:
                raise ValueError('invalid_sample_run')
            previous_end = sample
        if decoded != count or sp != se:
            raise ValueError('invalid_sample_count')
        samples += decoded
        for typ, at, _, _ in entries:
            if typ in (b'senc', b'saio', b'saiz'):
                out[at + 4:at + 8] = b'free'
    if samples == 0:
        raise ValueError('missing_media_samples')
    sidx = only(top, b'sidx')
    return bytes(out), dict(samples=samples, init_end=sidx[1] - 1,
                           index_start=sidx[1], index_end=sidx[3] - 1)


def byte_range(value, size):
    if value is None:
        return 0, size - 1
    if not value.startswith('bytes=') or ',' in value:
        raise ValueError('invalid_range')
    a, b = value[6:].split('-', 1)
    if not a:
        if not b.isascii() or not b.isdecimal() or int(b) == 0:
            raise ValueError('invalid_range')
        return max(0, size - int(b)), size - 1
    if not a.isascii() or not a.isdecimal() or (b and (not b.isascii() or not b.isdecimal())):
        raise ValueError('invalid_range')
    start, end = int(a), min(int(b), size - 1) if b else size - 1
    if not 0 <= start <= end < size:
        raise ValueError('invalid_range')
    return start, end


class MemoryMedia:
    """One episode, two bounded track buffers; no filesystem or external URL proxy."""
    def __init__(self, video, audio, video_index, audio_index, width, height, duration):
        if not 0 < duration <= 14400:
            raise ValueError('invalid_media_duration')
        self.token = secrets.token_urlsafe(32)
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def setup(self):
                super().setup()
                self.connection.settimeout(5)
            def log_message(self, *_):
                pass
            def do_HEAD(self):
                self.respond(False)
            def do_GET(self):
                self.respond(True)
            def respond(self, body):
                if self.headers.get('Host') != owner.host or self.path not in owner.files:
                    self.send_error(404)
                    return
                data, mime = owner.files[self.path]
                try:
                    start, end = byte_range(self.headers.get('Range'), len(data))
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(data)}')
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    return
                partial = self.headers.get('Range') is not None
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                if partial:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(memoryview(data)[start:end + 1])
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                self.close_connection = True
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.host = f'127.0.0.1:{self.server.server_port}'
        prefix = '/' + self.token + '/'
        def representation(kind, index):
            dims = f'width="{int(width)}" height="{int(height)}"' if kind == 'video' else ''
            return f'''<AdaptationSet contentType="{kind}" mimeType="{kind}/mp4"><Representation id="{kind}" bandwidth="2000000" {dims}>
                <BaseURL>{kind}.mp4</BaseURL><SegmentBase indexRange="{index['index_start']}-{index['index_end']}">
                <Initialization range="0-{index['init_end']}"/></SegmentBase></Representation></AdaptationSet>'''
        manifest = f'''<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
            profiles="urn:mpeg:dash:profile:isoff-on-demand:2011" minBufferTime="PT1S" mediaPresentationDuration="PT{duration}S">
            <Period duration="PT{duration}S">{representation('video', video_index)}{representation('audio', audio_index)}</Period></MPD>'''
        self.files = {prefix + 'video.mp4': (video, 'video/mp4'), prefix + 'audio.mp4': (audio, 'audio/mp4'),
                      prefix + 'manifest.mpd': (manifest.encode(), 'application/dash+xml')}
        self.address = 'http://' + self.host + prefix + 'manifest.mpd'

    def serve(self):
        self.server.serve_forever()

    def close(self):
        self.server.server_close()
