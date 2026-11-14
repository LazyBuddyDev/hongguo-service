import contextlib,importlib.util,json,math,pathlib,tempfile,unittest,sys,threading
from unittest.mock import patch
from lazybuddy_hongguo.backend import account as a
class Tests(unittest.TestCase):
 def test_explicit_sync_can_retry_but_final_flush_does_not_reset_a_failure(self):
  account=self.favorite_account();account.sync_error='progress_sync_failed'
  with patch.object(account,'sync_progress') as sync:
   account.call(dict(command='sync',flush=True));self.assertEqual(account.sync_error,'progress_sync_failed');sync.assert_not_called()
   account.call(dict(command='sync'));sync.assert_called_once();self.assertIsNone(account.sync_error)
 def test_stale_service_cannot_overwrite_another_services_newer_checkpoint(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root):
   older=self.favorite_account();newer=self.favorite_account()
   older.history={'12345':dict(episode=1,time=10.,updated=100.)}
   newer.call(dict(command='progress',series='12345',value=dict(episode=1,time=20.,updated=200.)))
   self.assertTrue(older.save_history());self.assertEqual(a.load_history('123')['12345']['time'],20.)
   self.assertEqual(older.history['12345']['time'],20.)
 def test_busy_cross_process_sync_does_not_block_or_duplicate_the_transaction(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root):
   account=self.favorite_account()
   with a.acquire(a.history_path('123').with_suffix('.sync-lock')) as locked:
    self.assertTrue(locked)
    with patch.object(account,'cloud') as cloud:
     account.sync_progress();cloud.assert_not_called()
   self.assertEqual(account.sync_state,'pending')
 def test_old_final_transaction_does_not_upload_a_new_services_playing_checkpoint(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_INSTANCE='default'):
   older=self.favorite_account();newer=self.favorite_account()
   older.history={'12345':dict(episode=1,time=10.,updated=100.,item='12346',duration=30.,count=2,synced=False)}
   def cloud(mode):
    newer.call(dict(command='progress',series='12345',value=dict(episode=1,time=20.,updated=200.),context=dict(item='12346',count=2,duration=30.)))
    return dict(code=0,video_data=[])
   with patch.object(older,'cloud',side_effect=cloud) as wire:older.sync_progress();self.assertEqual(wire.call_count,1)
   self.assertEqual(older.history['12345']['time'],20.);self.assertFalse(older.history['12345']['synced'])
 def test_cancelling_login_restores_saved_identity_without_deleting_credentials(self):
  x=a.Account()
  with patch.object(x.probe,'restore') as restore,patch.object(a.credentials,'delete') as delete:
   x.call(dict(command='cancel'));restore.assert_called_once();delete.assert_not_called()
  self.assertEqual(x.probe.state,'cancelled')
 def test_upload_does_not_hold_history_lock_or_confirm_a_newer_checkpoint(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_INSTANCE='default'):
   x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
   original=dict(episode=1,time=10.,updated=200.,item='12346',duration=30.,count=2,synced=False)
   x.history={'12345':original}
   entered=threading.Event();release=threading.Event();updated=threading.Event()
   def cloud(mode,progress=None):
    if mode=='progress_upload':entered.set();release.wait(3);return {'code':0}
    if not entered.is_set():return {'code':0,'video_data':[]}
    return {'code':0,'video_data':[dict(series_id='12345',vid='12346',vid_index=1,episode_count=2,last_watch_time=200,current_play_time=10000,current_total_time=30000)]}
   with patch.object(x,'cloud',side_effect=cloud):
    worker=threading.Thread(target=x.sync_progress);worker.start()
    try:
     self.assertTrue(entered.wait(2))
     def observe():
      x.call(dict(command='progress',series='12345',value=dict(episode=1,time=20.,updated=300.),context=dict(item='12346',count=2,duration=30.)))
      updated.set()
     observer=threading.Thread(target=observe);observer.start()
     self.assertTrue(updated.wait(1),'cloud upload blocked local playback checkpoints')
    finally:release.set();worker.join(4)
    observer.join(2)
   self.assertFalse(worker.is_alive());self.assertEqual(x.history['12345']['time'],20.)
   self.assertFalse(x.history['12345']['synced']);self.assertEqual(x.sync_state,'pending')
 def test_final_flush_skips_clean_history_but_keeps_dirty_and_explicit_reads(self):
  x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
  x.history={'12345':dict(episode=1,time=2.,updated=100.,synced=True)}
  with patch.object(x,'sync_progress') as sync:
   x.call({'command':'sync','flush':True});sync.assert_not_called()
   x.call({'command':'sync'});self.assertEqual(sync.call_count,1)
   x.history['12345']['synced']=False
   x.call({'command':'sync','flush':True});self.assertEqual(sync.call_count,2)
 def test_shelf_requires_real_schema_and_preserves_ids(self):
  row={'series_id':'7696437705822981182','series_title':'示例','series_cover_url':'https://p3-novel.byteimg.com/a','episode_cnt':222}
  result=a.parse_favorites({'code':0,'data':{'video_shelf_info':[row,row]}})
  self.assertEqual([(v['id'],v['episodes']) for v in result],[(row['series_id'],222)])
  self.assertEqual(a.parse_favorites({'code':0,'data':{'video_shelf_info':None}}),[])
  for value in ({'code':0,'data':None},{'code':0,'data':{}},{'code':1,'data':{'video_shelf_info':[]}}):
   with self.assertRaises(ValueError):a.parse_favorites(value)
 def test_failed_save_never_reports_signed_in(self):
  x=a.Account();x.probe.state='signed_in';x.probe.saved=False;x.probe.error='credential_save_failed'
  self.assertEqual(x.snapshot()['state'],'failed')
 def test_progress_is_per_account_atomic_and_validated(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root):
   x=a.Account();x.probe.state='signed_in';x.probe.saved=True;x.probe.uid='123';x.owner='123'
   x.call({'command':'progress','series':'12345','value':{'episode':4,'time':42.5,'updated':100.}})
   self.assertEqual(a.load_history('123')['12345']['time'],42.5)
   self.assertEqual(a.load_history('456'),{})
   self.assertFalse(list(pathlib.Path(root).glob('*.tmp')))
   self.assertNotEqual(a.history_path('123'),a.history_path('456'))
   for invalid in (float('nan'),float('inf'),-1,True):
    self.assertFalse(a.valid_progress({'episode':1,'time':invalid,'updated':1.}))
 def test_logout_clears_memory_and_only_calls_explicit_delete(self):
  x=a.Account();x.favorites=[{}];x.history={'fixture':{}};x.name='fixture';x.owner='123'
  with patch.object(a.credentials,'delete') as delete:
   x.call({'command':'logout'});delete.assert_called_once()
  self.assertEqual(x.favorites,[]);self.assertEqual(x.history,{});self.assertEqual(x.name,'')
 def test_corrupt_history_is_never_overwritten(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root),patch.object(a,'username',return_value='fixture'):
   x=a.Account();x.probe.state='signed_in';x.probe.saved=True;x.probe.uid='123'
   path=a.history_path('123');path.write_text('unreadable fixture',encoding='utf-8')
   self.assertEqual(x.snapshot()['error'],'history_invalid')
   x.probe.error=None
   x.call({'command':'progress','series':'12345','value':{'episode':1,'time':20.,'updated':100.}})
   self.assertEqual(path.read_text(encoding='utf-8'),'unreadable fixture')
 def test_write_failure_keeps_auth_and_original_file(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root):
   x=a.Account();x.probe.state='signed_in';x.probe.saved=True;x.probe.uid='123';x.owner='123'
   value={'episode':1,'time':20.,'updated':100.};x.call({'command':'progress','series':'12345','value':value})
   original=a.history_path('123').read_bytes()
   with patch.object(a.pathlib.Path,'write_text',side_effect=PermissionError):
    response=x.call({'command':'progress','series':'12345','value':dict(value,time=40.)})
   self.assertEqual(response['state'],'signed_in');self.assertEqual(response['error'],'history_save_failed')
   self.assertEqual(a.history_path('123').read_bytes(),original)
 def test_cloud_progress_requires_complete_schema_and_preserves_ids(self):
  row=dict(series_id='7696437705822981182',vid='7696437705822981183',vid_index=3,episode_count=222,
   last_watch_time=1700000000000,current_play_time=12500,current_total_time=30000)
  result=a.progress_rows({'code':0,'video_data':[row]});self.assertEqual(result[row['series_id']]['time'],12.5)
  self.assertEqual(result[row['series_id']]['updated'],1700000000.)
  for invalid in ({'code':0,'data':None},{'code':0,'video_data':[row]*500},{'code':1,'video_data':[]}):
   with self.assertRaises(ValueError):a.progress_rows(invalid)
 def test_sync_uses_newest_timestamp_and_uploads_only_dirty_local_progress(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_INSTANCE='default'):
   x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
   local=dict(episode=4,time=10.,updated=200.,item='12346',duration=30.,count=222,synced=False)
   x.history={'12345':local}
   remote=dict(series_id='12345',vid='12346',vid_index=4,episode_count=222,last_watch_time=100,current_play_time=5000,current_total_time=30000)
   confirmed=dict(remote,last_watch_time=200,current_play_time=10000)
   with patch.object(x,'cloud',side_effect=[{'code':0,'video_data':[remote]},{'code':0},{'code':0,'video_data':[confirmed]}]) as wire:
    x.sync_progress()
    self.assertEqual(wire.call_args_list[1].args[0],'progress_upload')
    self.assertTrue(x.history['12345']['synced']);self.assertEqual(x.sync_state,'synced')
   # A newer rewind in the official App takes priority over the higher local episode.
   remote.update(vid_index=1,vid='12347',last_watch_time=300,current_play_time=2000)
   with patch.object(x,'cloud',return_value={'code':0,'video_data':[remote]}) as wire:
    x.sync_progress();self.assertEqual(x.history['12345']['episode'],1);self.assertEqual(wire.call_count,1)
 def test_sync_failure_retains_pending_record_and_does_not_retry(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_INSTANCE='default'):
   x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
   x.history={'12345':dict(episode=1,time=10.,updated=200.,item='12346',duration=30.,count=222,synced=False)}
   with patch.object(x,'cloud',side_effect=[{'code':0,'video_data':[]},ValueError('rejected')]) as wire:
    x.sync_progress();x.sync_progress();self.assertEqual(wire.call_count,2)
   self.assertFalse(a.load_history('123')['12345']['synced']);self.assertEqual(x.sync_state,'failed')
 def test_isolated_progress_is_read_only_without_extra_write_authorization(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(a.os.environ,LAZYBUDDY_DATA_DIR=root,LAZYBUDDY_INSTANCE='qa',LAZYBUDDY_PROGRESS_REAL='0'):
   x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
   x.history={'12345':dict(episode=1,time=10.,updated=200.,item='12346',duration=30.,count=222,synced=False)}
   with patch.object(x,'cloud',return_value={'code':0,'video_data':[]}) as wire:
    x.sync_progress();self.assertEqual(wire.call_count,1)
   self.assertEqual(x.sync_state,'read_only');self.assertFalse(x.history['12345']['synced'])
 def favorite_account(self):
  x=a.Account();x.owner=x.probe.uid='123';x.probe.state='signed_in';x.probe.saved=True
  return x
 def test_favorite_add_and_remove_require_official_readback(self):
  row={'series_id':'7696437705822981182','series_title':'样例'}
  empty={'shelf':{'code':0,'data':{'video_shelf_info':[]}}};full={'shelf':{'code':0,'data':{'video_shelf_info':[row]}}}
  with patch.dict(a.os.environ,LAZYBUDDY_INSTANCE='default'):
   for add in (True,False):
    x=self.favorite_account()
    with patch.object(x,'request',side_effect=[empty if add else full,{'shelf':{'code':0}},full if add else empty]) as wire:
     response=x.call({'command':'favorite_set','series':row['series_id'],'favorite':add})
     self.assertIsNone(response['favorites_error']);self.assertEqual(bool(x.favorites),add)
     self.assertEqual(wire.call_args_list[1].args[0],'favorite_set')
     self.assertEqual(wire.call_args_list[1].kwargs,{'series':row['series_id'],'favorite':add})
 def test_favorite_write_never_claims_success_without_matching_readback(self):
  empty={'shelf':{'code':0,'data':{'video_shelf_info':[]}}}
  with patch.dict(a.os.environ,LAZYBUDDY_INSTANCE='default'):
   x=self.favorite_account()
   with patch.object(x,'request',side_effect=[empty,{'shelf':{'code':0}},empty]) as wire:
    response=x.call({'command':'favorite_set','series':'12345','favorite':True})
    self.assertEqual(wire.call_count,3);self.assertEqual(response['favorites_error'],'favorites_sync_failed');self.assertEqual(x.favorites,[])
   with patch.object(x,'request',side_effect=[empty,ValueError('denied')]) as wire:
    response=x.call({'command':'favorite_set','series':'12345','favorite':True})
    self.assertEqual(wire.call_count,2);self.assertEqual(response['state'],'signed_in')
 def test_favorite_writes_need_separate_permission_in_isolated_instances(self):
  x=self.favorite_account()
  with patch.dict(a.os.environ,LAZYBUDDY_INSTANCE='qa',LAZYBUDDY_FAVORITES_REAL='0',LAZYBUDDY_PROGRESS_REAL='1'),patch.object(x,'request') as wire:
   response=x.call({'command':'favorite_set','series':'12345','favorite':True})
   wire.assert_not_called();self.assertEqual(response['favorites_error'],'favorites_sync_failed')
 def test_favorite_set_is_idempotent_and_validates_target(self):
  x=self.favorite_account();empty={'shelf':{'code':0,'data':{'video_shelf_info':[]}}}
  with patch.dict(a.os.environ,LAZYBUDDY_INSTANCE='default'),patch.object(x,'request',return_value=empty) as wire:
   x.set_favorite('12345',False);wire.assert_called_once_with('favorites')
   for series,value in [('outside',True),('12345',1),('0',False)]:
    with self.assertRaises(ValueError):x.set_favorite(series,value)
if __name__=='__main__':unittest.main()
