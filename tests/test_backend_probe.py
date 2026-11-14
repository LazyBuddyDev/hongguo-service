import sys
from pathlib import Path
import importlib.util
import pathlib
import struct
import base64
import threading
import unittest
from unittest.mock import Mock, patch

from lazybuddy_hongguo.backend import passport as p

class Tests(unittest.TestCase):
    def test_redirect_allowlist(self):
        self.assertTrue(p.official('https://hongguoduanju.com/a'))
        self.assertTrue(p.official('https://www.hongguoduanju.com/a'))
        for value in ['http://hongguoduanju.com/','https://hongguoduanju.com.evil.test/',
                      'https://evil.test/?hongguoduanju.com','https://user@hongguoduanju.com/',
                      'https://hongguoduanju.com:81/','https://hongguoduanju.com/#token']:
            self.assertFalse(p.official(value))
    def test_passport_requires_explicit_success(self):
        self.assertEqual(p.payload('{"message":"success","data":{"error_code":0}}'),{'error_code':0})
        for value in ['{}','[]','{"message":"error","data":{}}','{"message":"success","data":{"error_code":4}}']:
            with self.assertRaises(ValueError):p.payload(value)
    def test_identity_is_exact_and_consistent(self):
        uid='7702763145030290457'
        self.assertEqual(p.identity({'user_id':int(uid),'user_id_str':uid}),uid)
        for value in [{},{'uid':0},{'uid':True},{'uid':'１２３'},{'uid':123,'user_id_str':'456'}]:
            with self.assertRaises(ValueError):p.identity(value)
    def test_qr_validation(self):
        image=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',200,200)
        self.assertEqual(p.qr_image(base64.b64encode(image).decode()),image)
        with self.assertRaises(ValueError):p.qr_image(base64.b64encode(b'not png').decode())
    def test_expiry_is_bounded(self):
        self.assertEqual(p.expiry(None,100),280)
        self.assertEqual(p.expiry(900,100),700)
        self.assertEqual(p.expiry(-1,100),100)
        self.assertEqual(p.expiry(1800000005,1800000000),1800000005)
    def test_cancel_discards_late_results(self):
        probe=p.Probe();old=probe.generation
        probe.cancel()
        self.assertFalse(probe.update(old,state='signed_in',fingerprint='wrong'))
        self.assertEqual(probe.status()['state'],'cancelled')
        self.assertIsNone(probe.status()['identity_fingerprint'])
    def test_status_does_not_export_credentials(self):
        probe=p.Probe();probe.client='cookie-secret';probe.image=b'qr-secret'
        state=str(probe.status())
        self.assertNotIn('cookie-secret',state);self.assertNotIn('qr-secret',state)
    def test_cancel_clears_session(self):
        probe=p.Probe();probe.client=object();probe.image=b'qr';probe.fingerprint='id';probe.state='signed_in'
        probe.cancel()
        self.assertIsNone(probe.client);self.assertFalse(probe.image)
        self.assertFalse(probe.status()['identity_verified'])
    def test_confirmed_qr_verifies_identity_before_success(self):
        probe=p.Probe()
        image=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',200,200)
        client=Mock()
        client.call.side_effect=[{'token':'private-token','qrcode':base64.b64encode(image).decode()},
                                 {'status':'confirmed','redirect_url':'https://hongguoduanju.com/'}]
        client.confirm.return_value='7702763145030290457'
        with patch.object(p,'Passport',return_value=client):
            probe.login(probe.generation,Mock(wait=Mock(return_value=False)))
        self.assertEqual(probe.state,'signed_in')
        client.confirm.assert_called_once()
        self.assertTrue(probe.status()['identity_verified'])
        self.assertNotIn('7702763145030290457',str(probe.status()))
        self.assertNotIn('private-token',str(probe.status()))
    def test_failed_identity_is_not_a_login(self):
        probe=p.Probe()
        image=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',200,200)
        client=Mock()
        client.call.side_effect=[{'token':'token','qrcode':base64.b64encode(image).decode()}, {'status':'confirmed'}]
        client.confirm.side_effect=ValueError('secret-response')
        with patch.object(p,'Passport',return_value=client):
            probe.login(probe.generation,Mock(wait=Mock(return_value=False)))
        self.assertEqual(probe.state,'failed')
        self.assertFalse(probe.status()['identity_verified'])
        self.assertIsNone(probe.client)
        self.assertNotIn('secret-response',str(probe.status()))
    def test_bad_ports_and_nonfinite_expiry_rejected(self):
        self.assertFalse(p.official('https://hongguoduanju.com:bad/'))
        with self.assertRaises(ValueError):p.expiry(float('nan'),100)
    def test_saved_session_schema_is_bounded_and_restores_only_official_cookies(self):
        record={'v':1,'uid':'123','cookies':{'sessionid':'fixture'}}
        restored=p.Passport.restore(record)
        self.assertEqual(restored.record('123'),record)
        cookie=list(restored.jar)[0]
        self.assertTrue(cookie.secure)
        self.assertEqual(cookie.domain,'.hongguoduanju.com')
        for value in [{'v':2,'uid':'123','cookies':{'sessionid':'x'}},
                      {'v':1,'uid':'0','cookies':{'sessionid':'x'}},
                      {'v':1,'uid':'123','cookies':{'unknown':'x'}},
                      {'v':1,'uid':'123','cookies':{'sessionid':'x\ny'}}]:
            with self.assertRaises(ValueError):p.credentials.validate(value)
    def test_save_requires_verified_matching_identity(self):
        probe=p.Probe(True)
        with patch.object(p.credentials,'save') as save:
            self.assertFalse(probe.save());save.assert_not_called()
            probe.state='signed_in';probe.uid='123';probe.client=Mock()
            with patch.object(p.Passport,'restore',return_value=Mock(confirm=Mock(return_value='456'))):
                self.assertFalse(probe.save());save.assert_not_called()
        self.assertEqual(probe.state,'signed_in')
        self.assertFalse(probe.saved)
    def test_restore_rejects_changed_identity_without_deleting_saved_credentials(self):
        probe=p.Probe(True)
        with patch.object(p.credentials,'read',return_value={'uid':'123'}),patch.object(p.Passport,'restore',return_value=Mock(confirm=Mock(return_value='456'))):
            probe.restore()
        self.assertFalse(probe.status()['identity_verified'])
        self.assertTrue(probe.saved)
        self.assertIsNone(probe.client)

if __name__=='__main__':unittest.main()
