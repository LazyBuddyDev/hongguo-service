"""Hongguo Passport identity and cancellable QR login with secure persistence."""
import base64
import hashlib
import http.cookiejar
import json
import math
import secrets
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from . import credentials

BASE = 'https://hongguoduanju.com'
PARAMS = dict(aid='513755', passport_jssdk_version='3.4.10', passport_jssdk_type='normal',
              account_sdk_source='web', is_from_ttaccountsdk='1', language='zh')
STATES = {'new': 'pending', 'pending': 'pending', '1': 'pending', '2': 'scanned',
          'scanned': 'scanned', '3': 'confirmed', 'confirmed': 'confirmed',
          '4': 'cancelled', 'cancelled': 'cancelled', '5': 'expired', 'expired': 'expired'}


def official(value):
    try:
        u = urllib.parse.urlsplit(value)
        return (u.scheme == 'https' and u.hostname is not None
                and (u.hostname == 'hongguoduanju.com' or u.hostname.endswith('.hongguoduanju.com'))
                and not u.username and not u.password and u.port in (None, 443) and not u.fragment)
    except ValueError:
        return False


def payload(body):
    data = json.loads(body)
    if not isinstance(data, dict) or data.get('message') != 'success':
        raise ValueError('passport_rejected')
    result = data.get('data')
    if not isinstance(result, dict) or str(result.get('error_code', 0)) != '0' or str(data.get('code', 0)) != '0':
        raise ValueError('passport_rejected')
    return result


def identity(data):
    ids = [str(data[k]) for k in ('user_id', 'uid', 'user_id_str') if data.get(k) is not None]
    if not ids or any(not v.isascii() or not v.isdecimal() or int(v) == 0 or len(v) > 32 for v in ids) or len(set(ids)) != 1:
        raise ValueError('invalid_identity')
    return ids[0]


def qr_image(value):
    raw = base64.b64decode(value.removeprefix('data:image/png;base64,'), validate=True)
    if len(raw) > 1024 * 1024 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
        raise ValueError('invalid_qr')
    w, h = struct.unpack('>II', raw[16:24])
    if not (32 <= w <= 2048 and 32 <= h <= 2048):
        raise ValueError('invalid_qr')
    return raw


def expiry(value, now):
    if value is None:
        return now + 180
    seconds = float(value)
    if not math.isfinite(seconds):
        raise ValueError('invalid_expiry')
    if seconds > 1e12:
        seconds = seconds / 1000 - now
    elif seconds > 1e9:
        seconds -= now
    return now + max(0, min(600, seconds))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Passport:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.name=''
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())

    def get(self, url):
        if not official(url):
            raise ValueError('untrusted_redirect')
        request = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
            'Referer': BASE + '/', 'Origin': BASE, 'Accept': 'application/json, text/javascript'})
        try:
            return self.client.open(request, timeout=10)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e
            raise ValueError('passport_http_' + str(e.code)) from None

    def call(self, path, **params):
        with self.get(BASE + path + '?' + urllib.parse.urlencode(PARAMS | params)) as response:
            if response.status != 200:
                raise ValueError('unexpected_redirect')
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('response_too_large')
        return payload(body)

    def confirm(self, redirect):
        if redirect:
            url = urllib.parse.urljoin(BASE + '/', redirect)
            for _ in range(5):
                with self.get(url) as response:
                    if response.status == 200:
                        break
                    location = response.headers.get('Location')
                    if not location:
                        raise ValueError('invalid_redirect')
                    url = urllib.parse.urljoin(url, location)
            else:
                raise ValueError('redirect_limit')
        if not any(c.name in ('sessionid', 'sessionid_ss') and c.value for c in self.jar):
            raise ValueError('missing_session')
        data=self.call('/passport/account/info/v2/')
        uid=identity(data)
        self.name=str(data.get('screen_name') or data.get('name') or '红果用户')[:80]
        return uid

    def record(self, uid):
        return credentials.validate(dict(v=1, uid=uid, cookies={c.name: c.value for c in self.jar
            if c.name in credentials.COOKIE_NAMES and c.value and official('https://' + c.domain.lstrip('.') + '/')}))

    @classmethod
    def restore(cls, record):
        credentials.validate(record)
        client = cls()
        for name, value in record['cookies'].items():
            client.jar.set_cookie(http.cookiejar.Cookie(0, name, value, None, False,
                '.hongguoduanju.com', True, True, '/', True, True, None, True, None, None, {'HttpOnly': None}))
        return client


class Probe:
    def __init__(self, persist=False):
        self.lock = threading.RLock()
        self.generation = 0
        self.cancelled = threading.Event()
        self.state = 'idle'
        self.image = b''
        self.deadline = 0
        self.client = None
        self.uid = None
        self.fingerprint = None
        self.error = None
        self.salt = secrets.token_bytes(32)
        self.persist = persist
        self.saved = False

    def status(self):
        with self.lock:
            return dict(state=self.state, expires_at=self.deadline, identity_verified=self.state == 'signed_in',
                        identity_fingerprint=self.fingerprint, error=self.error, credentials_persisted=self.saved,
                        app_account_verified=False, favorites_read=False, favorites_written=False)

    def cancel(self):
        with self.lock:
            self.generation += 1
            self.cancelled.set()
            self.image = b''
            self.client = None
            self.uid = None
            self.fingerprint = None
            self.saved = False
            self.state = 'cancelled'
            self.error = None

    def start(self):
        self.cancel()
        with self.lock:
            generation = self.generation
            self.cancelled = threading.Event()
            event = self.cancelled
            self.state = 'preparing'
            self.error = None
        threading.Thread(target=self.login, args=(generation, event), daemon=True).start()

    def update(self, generation, **values):
        with self.lock:
            if generation != self.generation:
                return False
            for key, value in values.items():
                setattr(self, key, value)
            return True

    def login(self, generation, event):
        try:
            client = Passport()
            data = client.call('/passport/web/get_qrcode/', next=BASE + '/')
            token = data.get('token')
            if not isinstance(token, str) or not 1 <= len(token) <= 8192:
                raise ValueError('invalid_qr_token')
            image = qr_image(data['qrcode'])
            deadline = expiry(data.get('expire_time'), time.time())
            if not self.update(generation, state='pending', image=image, deadline=deadline):
                return
            while time.time() < deadline and not event.wait(2):
                data = client.call('/passport/web/check_qrconnect/', next=BASE + '/', token=token)
                state = STATES.get(str(data.get('status')))
                if state is None:
                    raise ValueError('unknown_qr_state')
                if state == 'confirmed':
                    if not self.update(generation, state='verifying', image=b''):return
                    uid = client.confirm(data.get('redirect_url', ''))
                    fingerprint = hashlib.sha256(self.salt + uid.encode()).hexdigest()[:12]
                    if not self.update(generation,state='verifying' if self.persist else 'signed_in',client=client,uid=uid,fingerprint=fingerprint):return
                    if self.persist:self.save(generation)
                    return
                if not self.update(generation, state=state):
                    return
                if state in ('cancelled', 'expired'):
                    self.update(generation, image=b'')
                    return
            self.update(generation, state='expired', image=b'')
        except Exception:
            self.update(generation, state='failed', image=b'', error='login_step_failed')

    def save(self, generation=None):
        with self.lock:
            if generation is None:generation=self.generation
            if generation!=self.generation or self.state not in ('signed_in','verifying') or self.client is None:return False
            client,uid=self.client,self.uid
        try:
            record=client.record(uid)
            if Passport.restore(record).confirm('')!=uid:raise ValueError('saved_session_verification_failed')
            with self.lock:
                if generation!=self.generation:return False
                credentials.save(record)
                return self.update(generation,state='signed_in',saved=True,error=None)
        except Exception:
            with self.lock:
                if generation==self.generation:
                    self.error='credential_save_failed'
                    if self.state=='verifying':self.state='failed'
            return False

    def restore(self,cancelled=None):
        with self.lock:generation=self.generation
        try:
            if cancelled is not None and cancelled.is_set():return
            record = credentials.read()
            if record is None:
                return
            if not self.update(generation,saved=True):return
            client = Passport.restore(record)
            if cancelled is not None and cancelled.is_set():return
            uid = client.confirm('')
            if uid != record['uid']:
                raise ValueError('saved_identity_changed')
            self.update(generation,state='signed_in',client=client,uid=uid,
                        fingerprint=hashlib.sha256(self.salt+uid.encode()).hexdigest()[:12],error=None)
        except Exception as error:
            reason='invalid_credential_scope' if isinstance(error,ValueError) and error.args==('invalid_credential_scope',) else 'saved_session_verification_failed'
            self.update(generation,state='failed',error=reason)
