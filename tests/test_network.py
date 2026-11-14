import os,unittest
from unittest.mock import patch
from lazybuddy_hongguo.network import configure_helpers

class Tests(unittest.TestCase):
    def test_system_proxy_is_forwarded_only_to_service_children(self):
        with patch.dict(os.environ,{},clear=True),patch('urllib.request.getproxies',return_value={'https':'http://fixture:1234'}):
            configure_helpers()
            self.assertEqual(os.environ['HTTPS_PROXY'],'http://fixture:1234')

    def test_explicit_direct_mode_never_falls_back_to_registry(self):
        with patch.dict(os.environ,dict(HTTP_PROXY='',HTTPS_PROXY='',ALL_PROXY='',NO_PROXY='*'),clear=True),patch('urllib.request.getproxies_registry',side_effect=AssertionError('registry accessed'),create=True):
            configure_helpers()
            self.assertEqual(os.environ['HTTPS_PROXY'],'')
            self.assertEqual(os.environ['NO_PROXY'],'*')
