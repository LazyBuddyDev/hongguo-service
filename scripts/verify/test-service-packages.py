"""Install and invoke staged packages in isolation; no saved identity or upstream requests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
HOST_DIR=Path(os.environ['LAZYBUDDY_HOST_DIR']).resolve()
STAGED=Path(os.environ.get('LAZYBUDDY_PACKAGES_DIR',str(ROOT/'target/packages-dev')))
CLI=HOST_DIR/'lazybuddy-cli.exe'


class Packages(unittest.TestCase):
    def test_cover_worker_has_its_own_native_dependencies(self):
        program='''import sys,io,json
sys.path[:0]=sys.argv[1:]
from unittest.mock import MagicMock,patch
from PIL import Image
import pillow_heif
from lazybuddy_hongguo.covers import read
encoded=io.BytesIO();pillow_heif.from_pillow(Image.new('RGB',(480,640),(200,20,30))).save(encoded)
opener=MagicMock();response=opener.open.return_value.__enter__.return_value;response.status=200;response.read.return_value=encoded.getvalue()
with patch('lazybuddy_hongguo.covers.urllib.request.build_opener',return_value=opener):
    result=read('https://p3-novel.byteimg.com/fixture')
assert result['width']==240 and result['height']==320
print(json.dumps(dict(heic_worker=True,width=result['width'],height=result['height'])))
'''
        environment=dict(os.environ,PATH=str(Path(os.environ['SystemRoot'])/'System32'))
        environment.pop('PYTHONPATH',None)
        result=subprocess.run([str(STAGED/'python-runtime/bin/pythonw.exe'),'-I','-B','-c',program,
            str(STAGED/'hongguo/service'),str(STAGED/'hongguo/service/packages')],env=environment,
            capture_output=True,encoding='utf-8',errors='replace',timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['heic_worker'])

    def test_optional_services_run_without_source_checkout_imports(self):
        with tempfile.TemporaryDirectory(prefix='qa-service-packages-',dir=ROOT/'target') as temporary:
            environment=dict(os.environ,LAZYBUDDY_DATA_DIR=str(Path(temporary)/'data'),LAZYBUDDY_INSTANCE='qa-packages')
            environment.pop('PYTHONPATH',None)
            environment['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
            def call(*args):
                result=subprocess.run([str(CLI),*args],env=environment,capture_output=True,text=True,encoding='utf-8',
                    timeout=25,creationflags=subprocess.CREATE_NO_WINDOW,cwd=temporary)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            for identifier in ['python-runtime','media-runtime','hongguo','news']:
                call('modules','install-local',str(STAGED/identifier))
            for identifier in ['hongguo','news']:
                reply=call('call',identifier,json.dumps(dict(version=1,id='health',method='health')))
                self.assertTrue(reply['ok'])
            reply=call('call','hongguo',json.dumps(dict(version=1,id='account',method='account.status')))
            self.assertTrue(reply['ok'])
            self.assertEqual(reply['data']['state'],'idle')
            self.assertNotIn('owner',reply['data'])
            reply=call('call','news',json.dumps(dict(version=1,id='state',method='state')))
            self.assertTrue(reply['ok'])
            self.assertEqual(reply['data']['cache'],{})
            call('modules','uninstall','hongguo')
            self.assertEqual([module['id'] for module in call('modules','list')],['news'])
            call('modules','uninstall','news')
            self.assertEqual(call('modules','list'),[])


if __name__=='__main__':unittest.main()
