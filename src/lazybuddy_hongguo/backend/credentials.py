"""Current-user Windows Credential Manager: website session and separate App device."""
import ctypes
from ctypes import wintypes
import json
import os
import hashlib
import re

def prefix(scope):
    if scope and not re.fullmatch(r'[a-z0-9-]{1,48}',scope):raise ValueError('invalid_credential_scope')
    return 'LazyBuddy/Hongguo'+('/'+scope if scope else '')

PREFIX=prefix(os.environ.get('LAZYBUDDY_CREDENTIAL_SCOPE',''))
TARGET = PREFIX+'/website/v1'
COOKIE_NAMES = {'sessionid', 'sessionid_ss', 'sid_tt', 'uid_tt', 'uid_tt_ss', 'sid_guard',
                'passport_csrf_token', 'passport_csrf_token_default', 'passport_auth_status',
                'passport_auth_status_ss'}

class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def api():
    if os.name != 'nt':
        raise OSError('windows_credential_manager_required')
    dll = ctypes.WinDLL('advapi32', use_last_error=True)
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    return dll


def validate(record):
    if not isinstance(record, dict) or record.get('v') != 1:
        raise ValueError('invalid_saved_session')
    uid = record.get('uid')
    if not isinstance(uid, str) or not uid.isascii() or not uid.isdecimal() or not 1 <= len(uid) <= 32 or int(uid) == 0:
        raise ValueError('invalid_saved_identity')
    cookies = record.get('cookies')
    if not isinstance(cookies, dict) or not cookies or len(cookies) > len(COOKIE_NAMES):
        raise ValueError('invalid_saved_cookies')
    if not any(cookies.get(n) for n in ('sessionid', 'sessionid_ss')):
        raise ValueError('missing_saved_session')
    if any(n not in COOKIE_NAMES or not isinstance(v, str) or not v or len(v) > 2048
           or any(ord(c) < 32 or ord(c) == 127 for c in v) for n, v in cookies.items()):
        raise ValueError('invalid_saved_cookies')
    return record


def _read(target):
    dll = api()
    pointer = ctypes.POINTER(Credential)()
    if not dll.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise OSError('credential_read_failed')
    try:
        if not 1 <= pointer.contents.CredentialBlobSize <= 2560:
            raise ValueError('invalid_credential_size')
        return json.loads(ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize))
    finally:
        dll.CredFree(pointer)


def read():
    record = _read(TARGET)
    return validate(record) if record is not None else None


def save(record):
    validate(record)
    existing = read()
    if existing is not None and existing['uid'] != record['uid']:
        raise ValueError('saved_account_differs_delete_explicitly_first')
    _write(TARGET, record, 'LazyBuddy Hongguo website session')


def _write(target, record, comment):
    raw = json.dumps(record, separators=(',', ':')).encode()
    if len(raw) > 2560:
        raise ValueError('credential_too_large')
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    entry = Credential(Type=1, TargetName=target, Comment=comment,
                       CredentialBlobSize=len(raw), CredentialBlob=blob, Persist=2, UserName='LazyBuddy')
    try:
        if not api().CredWriteW(ctypes.byref(entry), 0):
            raise OSError('credential_write_failed')
    finally:
        ctypes.memset(blob, 0, len(raw))


def delete():
    record = read()
    if record is not None:
        _delete(device_target(record['uid']))
    _delete(TARGET)


def _delete(target):
    if not api().CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
        raise OSError('credential_delete_failed')


def device_target(uid):
    if not isinstance(uid, str) or not uid.isascii() or not uid.isdecimal() or not 1 <= len(uid) <= 32 or int(uid) == 0:
        raise ValueError('invalid_saved_identity')
    return PREFIX+'/device/v1/' + hashlib.sha256(uid.encode()).hexdigest()


def validate_device(profile):
    fields = {'cdid', 'openudid', 'clientudid', 'oaid_id', 'req_id', 'device_id_str', 'install_id_str',
              'device_token', 'ttreq', 'store_region', 'store_region_src', 'created_at', 'device'}
    if not isinstance(profile, dict) or profile.keys() - fields:
        raise ValueError('invalid_saved_device')
    for key, value in profile.items():
        if key != 'device' and (not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('invalid_saved_device')
    for key in ('device_id_str', 'install_id_str'):
        value = profile.get(key, '')
        if not value.isascii() or not value.isdecimal() or len(value) > 32 or int(value) == 0:
            raise ValueError('invalid_saved_device')
    if not all(profile.get(key) for key in ('cdid', 'openudid', 'clientudid', 'oaid_id', 'req_id', 'ttreq', 'created_at')):
        raise ValueError('invalid_saved_device')
    device = profile.get('device')
    if device is not None:
        fields = {'brand', 'model', 'os_version', 'os_api', 'build', 'resolution', 'dpi', 'pad', 'channel'}
        if not isinstance(device, dict) or device.keys() - fields:
            raise ValueError('invalid_saved_device')
        for key, value in device.items():
            expected = bool if key == 'pad' else int if key in ('os_api', 'dpi') else str
            if type(value) is not expected or (expected is str and (len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value))):
                raise ValueError('invalid_saved_device')
    return profile


def read_device(uid):
    record = _read(device_target(uid))
    if record is None:
        return None
    if not isinstance(record, dict) or record.keys() != {'v', 'uid', 'profile'} or record.get('v') != 1 or record.get('uid') != uid:
        raise ValueError('invalid_saved_device')
    return validate_device(record['profile'])


def remember_device(uid, profile):
    # Unscoped QA only reads the real device; a preview scope owns its cache.
    if os.environ.get('LAZYBUDDY_INSTANCE', 'default') != 'default' and PREFIX=='LazyBuddy/Hongguo':
        return False
    validate_device(profile)
    current = read()
    if current is None or current['uid'] != uid:
        return False
    existing = read_device(uid)
    if existing == profile:
        return True
    refreshed = {'ttreq', 'device_token', 'store_region', 'store_region_src'}
    if existing is not None and any(existing.get(key) != profile.get(key) for key in (existing.keys() | profile.keys()) - refreshed):
        return False
    try:
        _write(device_target(uid), dict(v=1, uid=uid, profile=profile), 'LazyBuddy Hongguo App device')
        return True
    except (OSError, ValueError):
        return False
