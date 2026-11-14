import sys
from pathlib import Path
import importlib.util,io,pathlib,struct,sys,unittest
from lazybuddy_hongguo.backend import cover as cover
from PIL import Image
import pillow_heif
class Tests(unittest.TestCase):
 def test_heic_is_a_bounded_rgba_thumbnail(self):
  encoded=io.BytesIO();pillow_heif.from_pillow(Image.new('RGB',(480,640),(200,20,30))).save(encoded)
  output=cover.decode(encoded.getvalue());w,h=struct.unpack('>II',output[:8]);self.assertEqual((w,h),(240,320));self.assertEqual(len(output),8+w*h*4)
  self.assertGreater(output[8],150);self.assertEqual(output[11],255)
 def test_invalid_or_oversize_input_is_rejected(self):
  for value in (b'',b'not an image',b'0'*(4*1024*1024+1)):
   with self.assertRaises(Exception):cover.decode(value)
if __name__=='__main__':unittest.main()
