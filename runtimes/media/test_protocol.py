import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch,Mock

spec=importlib.util.spec_from_file_location('media',Path(__file__).with_name('lazybuddy_media.py'))
media=importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class Protocol(unittest.TestCase):
    def test_decoded_size_reads_negotiated_caps_and_releases_its_reference(self):
        runtime=Mock();player=media.Player(runtime);player.video_pad=1
        runtime.gst.gst_pad_get_current_caps.return_value=2;runtime.gst.gst_caps_get_structure.return_value=3
        def integer(structure,key,target):
            media.ctypes.cast(target,media.ctypes.POINTER(media.ctypes.c_int))[0]=320 if key==b'width' else 180
            return 1
        runtime.gst.gst_structure_get_int.side_effect=integer
        self.assertEqual(player.decoded_size(),(320,180));runtime.gst.gst_mini_object_unref.assert_called_once_with(2)
        runtime.gst.gst_pad_get_current_caps.return_value=None
        self.assertEqual(player.decoded_size(),(None,None));runtime.gst.gst_mini_object_unref.assert_called_once()
    def test_temporary_rate_preserves_selection_and_pause_restores_it(self):
        runtime=Mock();runtime.gst.gst_element_get_state.return_value=1;runtime.gst.gst_element_seek.return_value=1
        player=media.Player(runtime);player.pipeline=1
        with patch.object(player,'state',return_value=dict(position=10.)):
            player.command('speed',dict(value=1.5));player.command('boost',dict(value=True))
            self.assertEqual((player.rate,player.actual_rate,player.boosted),(1.5,2.,True))
            player.command('seek',dict(value=20.))
            self.assertEqual(runtime.gst.gst_element_seek.call_args.args[1],2.)
            player.command('pause',{})
            self.assertEqual((player.rate,player.actual_rate,player.boosted),(1.5,1.5,False))
    def test_default_speed_does_not_seek_before_the_pipeline_prerolls(self):
        runtime=Mock();player=media.Player(runtime);player.pipeline=1
        with patch.object(player,'state',return_value=dict(loaded=False)):
            self.assertEqual(player.command('speed',dict(value=1.)),dict(loaded=False))
        runtime.gst.gst_element_seek.assert_not_called()
        runtime.gst.gst_element_get_state.assert_not_called()
        with self.assertRaises(ValueError):player.command('speed',dict(value=True))
    def test_health_and_invalid_requests_never_load_decoder(self):
        requests=[dict(version=1,id='health',method='health'),dict(version=True,id='bad',method='health'),
                  dict(version=1,id='unknown',method='arbitrary'),dict(version=1,id='extra',method='health',args=dict(url='SECRET'))]
        stdin=io.TextIOWrapper(io.BytesIO(('\n'.join(map(json.dumps,requests))+'\n').encode()))
        stdout=io.StringIO()
        with patch.object(media.sys,'stdin',stdin),contextlib.redirect_stdout(stdout),patch.object(media,'Gst',side_effect=AssertionError('decoder must remain unloaded')):
            media.main()
        replies=list(map(json.loads,stdout.getvalue().splitlines()))
        self.assertTrue(replies[0]['ok'])
        self.assertEqual([reply['error']['code'] for reply in replies[1:]],['invalid_request','unknown_method','invalid_request'])
        self.assertNotIn('SECRET',stdout.getvalue())


if __name__=='__main__':unittest.main()
