import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from lazybuddy_hongguo import diagnostics as d
class Tests(unittest.TestCase):
 def test_error_details_are_pure_and_redacted(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_LOG_DIR=root):
   try:raise ValueError('SECRET')
   except ValueError as error:row=d.describe('media_request_failed',stage='prepare',exception=error)
   self.assertEqual(row['exception_type'],'ValueError');self.assertTrue(row['stack']);self.assertNotIn('SECRET',json.dumps(row));self.assertEqual(list(Path(root).iterdir()),[])
 def test_response_metadata_and_urls_are_filtered(self):
  row=d.describe('media_redirect_target_rejected',stage='redirect',source='https://user:SECRET@safe.example/private?token=SECRET',response_meta={'content_type':'application/json','declared_length':0,'cookie':'SECRET','content_encoding':'SECRET'})
  self.assertNotIn('SECRET',json.dumps(row));self.assertEqual(row['source_host'],'safe.example');self.assertEqual(row['response_meta'],{'content_type':'application/json','declared_length':0})
 def test_service_api_error_returns_diagnostics_without_files(self):
  from lazybuddy_hongguo.protocol import Service
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_LOG_DIR=root):
   service=Service(lambda:None);reply=service.handle({'version':99,'method':'health'});service.close()
   self.assertFalse(reply['ok']);self.assertEqual(reply['error']['diagnostic']['stage'],'api');self.assertEqual(list(Path(root).iterdir()),[])
 def test_exception_carries_read_status(self):
  error=d.failure('app_playback_empty_response',stage='playback',status=200,body_bytes=0,body_read_ok=True)
  self.assertEqual(error.args[0],'app_playback_empty_response');self.assertTrue(error.diagnostic['body_read_ok'])
