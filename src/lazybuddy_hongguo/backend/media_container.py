"""Shared bounds checks for the progressive MP4 reader."""
import re


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
