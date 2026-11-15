import os,tempfile,unittest,struct
from pathlib import Path
from unittest.mock import patch
from lazybuddy_hongguo import covers as c

class Tests(unittest.TestCase):
 def test_persistent_cache_skips_download_and_corruption_is_refetched(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=directory),patch.object(c,'_download',return_value=dict(width=1,height=1,rgba='/wAA/w==')) as download:
   url='https://one.byteimg.com/image?signature=SECRET'
   self.assertEqual(c.read(url),c.read(url));self.assertEqual(download.call_count,1)
   path=next((Path(directory)/'cache/covers').glob('*.rgba'))
   self.assertNotIn('SECRET',path.name);self.assertEqual(path.read_bytes(),struct.pack('>II',1,1)+bytes([255,0,0,255]))
   path.write_bytes(b'broken');c.read(url);self.assertEqual(download.call_count,2)
 def test_bound_expiry_and_invalid_sources(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=directory),patch.object(c,'MAX_CACHE_FILES',2),patch.object(c,'_download',return_value=dict(width=1,height=1,rgba='/wAA/w==')) as download:
   for i in range(4):c.read('https://one.byteimg.com/'+str(i))
   files=list((Path(directory)/'cache/covers').glob('*.rgba'));self.assertEqual(len(files),2)
   for path in files:os.utime(path,(0,0))
   c.read('https://one.byteimg.com/3');self.assertEqual(download.call_count,5)
   with self.assertRaises(ValueError):c.read('https://unknown.invalid/x')

 def test_series_cache_survives_source_table_loss_without_network(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=directory),patch.object(c,'_download',return_value=dict(width=1,height=1,rgba='/wAA/w==')) as download:
   expected=c.read('https://one.byteimg.com/image?signature=SECRET',series='123')
   self.assertEqual(c.read_cached('123'),expected);self.assertEqual(download.call_count,1)
   with self.assertRaises(ValueError):c.read_cached('456')
   for series in ('../123','0','1'*33,None):
    with self.assertRaises(ValueError):c.read_cached(series)
   self.assertEqual(download.call_count,1)
   path=next((Path(directory)/'cache/covers').glob('*.rgba'));path.write_bytes(b'broken')
   with self.assertRaises(ValueError):c.read_cached('123')
   self.assertEqual(download.call_count,1)
