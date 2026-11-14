import sys
from pathlib import Path
"""Synthetic-only CENC, malformed input and private range service checks."""
import base64
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from lazybuddy_hongguo.backend import media_container as m


def box(kind, body):
    return (len(body) + 8).to_bytes(4, 'big') + kind + body


def fixture(key, audio=False, iv_size=8, subsamples=True, dual=False):
    clear = b'clear' + b'own-synthetic-sample' * 2
    iv = bytes(range(iv_size))
    cipher = m.Cipher(m.algorithms.AES(key), m.modes.CTR(iv + b'\0' * (16 - iv_size))).encryptor()
    lead = 5 if subsamples else 0
    encrypted = clear[:lead] + cipher.update(clear[lead:]) + cipher.finalize()
    tenc = box(b'tenc', b'\0' * 4 + b'\0\0\1' + bytes([iv_size]) + b'\0' * 16)
    sinf = box(b'sinf', box(b'frma', b'mp4a' if audio else b'avc1') + box(b'schm', b'\0' * 4 + b'cenc' + b'\0' * 4) + box(b'schi', tenc))
    entry = box(b'enca' if audio else b'encv', b'\0' * (28 if audio else 78) + sinf)
    extra = box(b'mp4a' if audio else b'avc1', b'\0' * (28 if audio else 78)) if dual else b''
    moov = box(b'moov', box(b'trak', box(b'mdia', box(b'minf', box(b'stbl', box(b'stsd', b'\0' * 4 + (2 if dual else 1).to_bytes(4,'big') + entry + extra))))))
    tfhd = box(b'tfhd', (0x20000).to_bytes(4,'big') + (1).to_bytes(4,'big'))
    senc = box(b'senc', (2 if subsamples else 0).to_bytes(4,'big') + (1).to_bytes(4,'big') + iv +
               ((1).to_bytes(2,'big') + lead.to_bytes(2,'big') + (len(clear)-lead).to_bytes(4,'big') if subsamples else b''))
    def fragment(offset):
        trun = box(b'trun', (0x201).to_bytes(4,'big') + (1).to_bytes(4,'big') + offset.to_bytes(4,'big') + len(clear).to_bytes(4,'big'))
        return box(b'moof', box(b'traf', tfhd + trun + senc))
    moof = fragment(len(fragment(0)) + 8)
    data = box(b'ftyp',b'isom' + b'\0'*4) + moov + box(b'sidx',b'\0'*24) + moof + box(b'mdat',encrypted)
    return data, clear


def wrap_fixture(key):
    desired = b'1' + key.hex().encode() + b'1'
    previous, current = 0x55, 0xfa
    encoded = bytearray()
    for i, target in enumerate(desired):
        term = 0x15 + i.bit_count()
        b = ((target - term) & 255) ^ (current if i % 2 == 0 else previous)
        encoded.append(b)
        if i % 2 == 0:current=b
        else:previous=b
    tag = b'22'
    raw = bytes([(0x30+len(tag)) ^ encoded[0] ^ encoded[1]]) + encoded
    raw += bytes(raw[-2] ^ raw[-1] ^ b for b in tag)
    return base64.b64encode(raw).decode()


class Tests(unittest.TestCase):
    def test_wrapped_website_material_synthetic(self):
        self.assertEqual(m.wrapped_key(wrap_fixture(b'\x11'*16)),b'\x11'*16)
        for bad in ('','not base64','AAAA','MDAwMDAwMDAwMDAw'):
            with self.assertRaises(ValueError):m.wrapped_key(bad)

    def test_subsample_and_full_sample_ivs_keep_offsets(self):
        for audio in (False,True):
            for iv in (8,16):
                for subsamples in (False,True):
                    source, expected = fixture(b'\x11'*16,audio,iv,subsamples)
                    out,index=m.prepare_track(source,b'\x11'*16)
                    self.assertEqual(len(out),len(source))
                    self.assertEqual(out[-len(expected):],expected)
                    self.assertNotIn(b'enca' if audio else b'encv',out)
                    self.assertNotIn(b'senc',out)
                    self.assertEqual(index['samples'],1)

    def test_malformed_and_unsupported_inputs_fail(self):
        source,_=fixture(b'\x11'*16)
        for data in (b'',source[:-1],source.replace(b'cenc',b'cbcs'),source.replace(b'senc',b'free'),source.replace(b'trun',b'free')):
            with self.assertRaises(ValueError):m.prepare_track(data,b'\x11'*16)
        # Reject a subsample range crossing the sample, not merely the file boundary.
        bad=bytearray(source);s=bad.index(b'senc');bad[s+4+8+8+2+2:s+4+8+8+2+6]=(999999).to_bytes(4,'big')
        with self.assertRaises(ValueError):m.prepare_track(bad,b'\x11'*16)

    def test_dual_sample_descriptions_keep_track_offsets(self):
        for audio in (False,True):
            source,expected=fixture(b'\x11'*16,audio=audio,dual=True)
            out,index=m.prepare_track(source,b'\x11'*16)
            self.assertEqual(len(out),len(source))
            self.assertEqual(out[-len(expected):],expected)
            self.assertEqual(index['samples'],1)

    def test_range_bounds(self):
        for value,expected in [(None,(0,9)),('bytes=2-4',(2,4)),('bytes=8-',(8,9)),('bytes=-3',(7,9)),('bytes=8-99',(8,9))]:
            self.assertEqual(m.byte_range(value,10),expected)
        for value in ('bytes=10-','bytes=3-2','bytes=0-1,3-4','bytes=-0','bytes=bad','other=0-1'):
            with self.assertRaises(ValueError):m.byte_range(value,10)

    def test_private_server_head_ranges_and_missing_token(self):
        index=dict(index_start=8,index_end=15,init_end=7)
        server=m.MemoryMedia(b'1234567890',b'abcdefghij',index,index,1280,720,10)
        worker=threading.Thread(target=server.serve,daemon=True);worker.start()
        try:
            url=server.address.replace('manifest.mpd','audio.mp4')
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=2-4'})) as r:
                self.assertEqual(r.status,206);self.assertEqual(r.read(),b'cde')
            with urllib.request.urlopen(urllib.request.Request(url,method='HEAD')) as r:
                self.assertEqual(r.headers['Content-Length'],'10');self.assertEqual(r.read(),b'')
            for bad in ('http://'+server.host+'/audio.mp4',server.address+'?other=1'):
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(bad)
                self.assertEqual(e.exception.code,404)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(url,headers={'Host':'other.invalid'}))
            self.assertEqual(e.exception.code,404)
        finally:
            server.server.shutdown();server.close();worker.join()


if __name__=='__main__':unittest.main()
