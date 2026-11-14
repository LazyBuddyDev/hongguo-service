"""Private Windows GStreamer control service. Pixel transport uses D3D12 IPC."""
import ctypes
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import urllib.parse

NS = 1_000_000_000


class GError(ctypes.Structure):
    _fields_ = [('domain', ctypes.c_uint), ('code', ctypes.c_int), ('message', ctypes.c_void_p)]


class Gst:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.dll_directory = os.add_dll_directory(str(self.directory / 'bin'))
        os.environ['PATH'] = str(self.directory / 'bin') + ';' + os.environ.get('PATH', '')
        os.environ['GST_PLUGIN_SYSTEM_PATH_1_0'] = str(self.directory / 'lib/gstreamer-1.0')
        os.environ['GST_PLUGIN_PATH_1_0'] = ''
        os.environ['GST_PLUGIN_SCANNER_1_0'] = str(self.directory / 'libexec/gstreamer-1.0/gst-plugin-scanner.exe')
        os.environ['GST_DEBUG'] = '0'
        self.gst = ctypes.CDLL(str(self.directory / 'bin/gstreamer-1.0-0.dll'))
        self.object = ctypes.CDLL(str(self.directory / 'bin/gobject-2.0-0.dll'))
        self.glib = ctypes.CDLL(str(self.directory / 'bin/glib-2.0-0.dll'))
        pointer = ctypes.c_void_p
        self.function('gst_init_check', ctypes.c_int, [pointer, pointer, pointer])
        self.function('gst_parse_bin_from_description', pointer, [ctypes.c_char_p, ctypes.c_int, pointer])
        self.function('gst_element_factory_make', pointer, [ctypes.c_char_p, ctypes.c_char_p])
        self.function('gst_object_ref_sink', pointer, [pointer])
        self.function('gst_object_unref', None, [pointer])
        self.function('gst_bin_get_by_name', pointer, [pointer, ctypes.c_char_p])
        self.function('gst_element_get_static_pad',pointer,[pointer,ctypes.c_char_p])
        self.function('gst_pad_get_current_caps',pointer,[pointer])
        self.function('gst_caps_get_structure',pointer,[pointer,ctypes.c_uint])
        self.function('gst_structure_get_int',ctypes.c_int,[pointer,ctypes.c_char_p,pointer])
        self.function('gst_mini_object_unref',None,[pointer])
        self.function('gst_element_set_state', ctypes.c_int, [pointer, ctypes.c_int])
        self.function('gst_element_get_state', ctypes.c_int, [pointer, pointer, pointer, ctypes.c_uint64])
        self.function('gst_element_query_position', ctypes.c_int, [pointer, ctypes.c_int, pointer])
        self.function('gst_element_query_duration', ctypes.c_int, [pointer, ctypes.c_int, pointer])
        self.function('gst_element_seek', ctypes.c_int, [pointer, ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int64, ctypes.c_int, ctypes.c_int64])
        self.function('gst_element_get_bus', pointer, [pointer])
        self.function('gst_bus_add_signal_watch', None, [pointer])
        self.function('gst_bus_remove_signal_watch', None, [pointer])
        self.function('gst_message_parse_error', None, [pointer, pointer, pointer])
        self.glib.g_main_loop_new.argtypes = [pointer, ctypes.c_int]
        self.glib.g_main_loop_new.restype = pointer
        for name in ('g_main_loop_run', 'g_main_loop_quit', 'g_main_loop_unref'):
            getattr(self.glib, name).argtypes = [pointer]
        self.glib.g_error_free.argtypes = [pointer]
        self.glib.g_free.argtypes = [pointer]
        self.glib.g_quark_to_string.argtypes = [ctypes.c_uint]
        self.glib.g_quark_to_string.restype = ctypes.c_char_p
        self.object.g_object_set.argtypes = [pointer, ctypes.c_char_p]
        self.object.g_signal_connect_data.argtypes = [pointer, ctypes.c_char_p, pointer, pointer, pointer, ctypes.c_uint]
        self.object.g_signal_connect_data.restype = ctypes.c_ulong
        if not self.gst.gst_init_check(None, None, None):
            raise ValueError('media_runtime_init_failed')

    def function(self, name, result, arguments):
        function = getattr(self.gst, name)
        function.restype = result
        function.argtypes = arguments

    def bin(self, description):
        error = ctypes.c_void_p()
        element = self.gst.gst_parse_bin_from_description(description.encode(), True, ctypes.byref(error))
        if error.value:
            self.glib.g_error_free(error)
            if element:
                self.gst.gst_object_unref(element)
            raise ValueError('media_pipeline_unavailable')
        if not element:
            raise ValueError('media_pipeline_unavailable')
        return self.gst.gst_object_ref_sink(element)


class Player:
    def __init__(self, runtime):
        self.runtime = runtime
        self.pipeline = None
        self.bus = None
        self.loop = None
        self.thread = None
        self.callbacks = []
        self.eos = threading.Event()
        self.failed = threading.Event()
        self.rate = 1.0
        self.actual_rate=1.0
        self.boosted=False
        self.error_detail = None
        self.video_pad=None

    def on_error(self, _bus, message, _data):
        error = ctypes.POINTER(GError)()
        debug = ctypes.c_void_p()
        self.runtime.gst.gst_message_parse_error(message, ctypes.byref(error), ctypes.byref(debug))
        if error:
            domain = self.runtime.glib.g_quark_to_string(error.contents.domain)
            self.error_detail = dict(domain=domain.decode('ascii', errors='replace') if domain else 'unknown', code=error.contents.code)
            self.runtime.glib.g_error_free(error)
        if debug:
            self.runtime.glib.g_free(debug)
        self.failed.set()

    def open(self, uri, pipe):
        parsed = urllib.parse.urlsplit(uri)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError('private_media_source_required')
        if not re.fullmatch(r'\\\\\.\\pipe\\lazybuddy-media-[a-f0-9]{16,64}', pipe):
            raise ValueError('invalid_media_pipe')
        self.close()
        gst = self.runtime.gst
        pipeline = gst.gst_element_factory_make(b'playbin', b'lazybuddy-player')
        if not pipeline:
            raise ValueError('media_pipeline_unavailable')
        self.pipeline = gst.gst_object_ref_sink(pipeline)
        video = self.runtime.bin('d3d12upload ! d3d12convert ! video/x-raw(memory:D3D12Memory),format=RGBA,colorimetry=sRGB ! d3d12ipcsink name=output')
        sink = gst.gst_bin_get_by_name(video, b'output')
        try:
            self.video_pad=gst.gst_element_get_static_pad(sink,b'sink')
            self.runtime.object.g_object_set(sink, b'pipe-name', ctypes.c_char_p(pipe.encode()), None)
            self.runtime.object.g_object_set(self.pipeline, b'video-sink', ctypes.c_void_p(video), None)
        finally:
            gst.gst_object_unref(sink)
            gst.gst_object_unref(video)
        audio = self.runtime.bin('audioconvert ! scaletempo ! audioresample ! autoaudiosink')
        try:
            self.runtime.object.g_object_set(self.pipeline, b'audio-sink', ctypes.c_void_p(audio), None)
        finally:
            gst.gst_object_unref(audio)
        self.runtime.object.g_object_set(self.pipeline, b'uri', ctypes.c_char_p(uri.encode()), None)
        self.bus = gst.gst_element_get_bus(self.pipeline)
        self.loop = self.runtime.glib.g_main_loop_new(None, False)
        callback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        for signal, event in ((b'message::eos', self.eos), (b'message::error', self.failed)):
            handler = callback(self.on_error if signal == b'message::error' else lambda _bus, _message, _data, event=event: event.set())
            self.callbacks.append(handler)
            self.runtime.object.g_signal_connect_data(self.bus, signal, handler, None, None, 0)
        gst.gst_bus_add_signal_watch(self.bus)
        self.thread = threading.Thread(target=self.runtime.glib.g_main_loop_run, args=(self.loop,), daemon=True)
        self.thread.start()
        if gst.gst_element_set_state(self.pipeline, 3) == 0:
            self.close()
            raise ValueError('media_load_failed')

    def decoded_size(self):
        if not self.video_pad:return None,None
        gst=self.runtime.gst;caps=gst.gst_pad_get_current_caps(self.video_pad)
        if not caps:return None,None
        try:
            structure=gst.gst_caps_get_structure(caps,0)
            width,height=ctypes.c_int(),ctypes.c_int()
            if structure and gst.gst_structure_get_int(structure,b'width',ctypes.byref(width)) and gst.gst_structure_get_int(structure,b'height',ctypes.byref(height)) and width.value>0 and height.value>0:
                return width.value,height.value
            return None,None
        finally:gst.gst_mini_object_unref(caps)

    def state(self):
        if not self.pipeline:
            return dict(loaded=False, playing=False, eos=False, error=None, position=0, duration=0, speed=self.rate,actual_speed=self.actual_rate,boosted=self.boosted,decoded_width=None,decoded_height=None)
        current = ctypes.c_int()
        pending = ctypes.c_int()
        self.runtime.gst.gst_element_get_state(self.pipeline, ctypes.byref(current), ctypes.byref(pending), 0)
        position, duration = ctypes.c_int64(), ctypes.c_int64()
        self.runtime.gst.gst_element_query_position(self.pipeline, 3, ctypes.byref(position))
        self.runtime.gst.gst_element_query_duration(self.pipeline, 3, ctypes.byref(duration))
        width,height=self.decoded_size()
        return dict(loaded=current.value >= 3, playing=current.value == 4, eos=self.eos.is_set(),decoded_width=width,decoded_height=height,
                    error='media_failed' if self.failed.is_set() else None,
                    diagnostic=self.error_detail,
                    position=max(0, position.value) / NS, duration=max(0, duration.value) / NS, speed=self.rate,actual_speed=self.actual_rate,boosted=self.boosted)

    def command(self, method, args):
        if method == 'close':
            self.close()
            return self.state()
        if not self.pipeline:
            raise ValueError('media_not_loaded')
        gst = self.runtime.gst
        if method in ('play', 'pause'):
            if gst.gst_element_set_state(self.pipeline, 4 if method == 'play' else 3) == 0:
                raise ValueError('media_state_failed')
            if method=='pause' and gst.gst_element_get_state(self.pipeline,None,None,5*NS) in (0,2):
                raise ValueError('media_state_failed')
            if method=='pause' and self.boosted:self.command('boost',dict(value=False))
        elif method=='boost':
            value=args.get('value')
            if type(value) is not bool:raise ValueError('invalid_value')
            selected=self.rate;target=2. if value else selected
            try:
                if target!=self.actual_rate:self.command('speed',dict(value=target))
            except Exception:
                self.close();raise
            self.rate=selected;self.boosted=value
        elif method in ('seek', 'speed'):
            value = args.get('value')
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('invalid_value')
            if method == 'speed':
                if not 0.25 <= value <= 4:
                    raise ValueError('invalid_speed')
                if value==self.actual_rate:
                    self.rate=float(value);self.boosted=False;return self.state()
            if gst.gst_element_get_state(self.pipeline,None,None,5*NS) in (0,2):
                raise ValueError('media_seek_failed')
            if method == 'speed':
                rate, position = float(value), self.state()['position']
            else:
                if not 0 <= value <= 86400:
                    raise ValueError('invalid_seek')
                rate, position = self.actual_rate, float(value)
            if not gst.gst_element_seek(self.pipeline, rate, 3, 3, 1, int(position * NS), 0, 0):
                raise ValueError('media_seek_failed')
            # Finish the flush before a following speed command reads the position.
            if gst.gst_element_get_state(self.pipeline, None, None, 5 * NS) in (0, 2):
                raise ValueError('media_seek_failed')
            self.actual_rate=rate
            if method=='speed':self.rate=rate;self.boosted=False
            self.eos.clear()
        elif method == 'volume':
            value = args.get('value')
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('invalid_volume')
            self.runtime.object.g_object_set(self.pipeline, b'volume', ctypes.c_double(value), None)
        elif method == 'mute':
            value = args.get('value')
            if type(value) is not bool:
                raise ValueError('invalid_mute')
            self.runtime.object.g_object_set(self.pipeline, b'mute', ctypes.c_int(value), None)
        elif method != 'status':
            raise ValueError('unknown_method')
        return self.state()

    def close(self):
        if self.pipeline:
            self.runtime.gst.gst_element_set_state(self.pipeline, 1)
            self.runtime.gst.gst_element_get_state(self.pipeline, None, None, 5 * NS)
        if self.bus:
            self.runtime.gst.gst_bus_remove_signal_watch(self.bus)
        if self.loop:
            self.runtime.glib.g_main_loop_quit(self.loop)
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise ValueError('media_thread_stop_failed')
        if self.bus:
            self.runtime.gst.gst_object_unref(self.bus)
        if self.video_pad:
            self.runtime.gst.gst_object_unref(self.video_pad)
            self.video_pad=None
        if self.pipeline:
            self.runtime.gst.gst_object_unref(self.pipeline)
        if self.loop:
            self.runtime.glib.g_main_loop_unref(self.loop)
        self.pipeline = self.bus = self.loop = self.thread = None
        self.callbacks.clear()
        self.eos.clear()
        self.failed.clear()
        self.rate = 1.0
        self.actual_rate=1.0
        self.boosted=False
        self.error_detail = None


def main():
    directory = os.environ.get('LAZYBUDDY_GSTREAMER_DIR') or str(Path(__file__).resolve().parent / 'runtime')
    player = None
    try:
        while line := sys.stdin.buffer.readline(65537):
            request = {}
            try:
                if len(line) > 65536:
                    raise ValueError('request_too_large')
                request = json.loads(line)
                if (not isinstance(request, dict) or set(request)-{'version','id','method','args'}
                        or type(request.get('version')) is not int or request.get('version') != 1 or not isinstance(request.get('id'), str)):
                    raise ValueError('invalid_request')
                method = request.get('method')
                args = request.get('args', {})
                if not isinstance(args, dict):
                    raise ValueError('invalid_request')
                allowed={'health':set(),'open':{'uri','pipe'},'close':set(),'play':set(),'pause':set(),'status':set(),
                         'seek':{'value'},'speed':{'value'},'boost':{'value'},'volume':{'value'},'mute':{'value'}}
                if not isinstance(method,str) or method not in allowed:
                    raise ValueError('unknown_method')
                if set(args)-allowed[method]:
                    raise ValueError('invalid_request')
                if method == 'health':
                    data = dict(service='media', api_version=1)
                else:
                    if player is None:
                        player = Player(Gst(directory))
                    if method == 'open':
                        player.open(args.get('uri', ''), args.get('pipe', ''))
                        data = dict(producer_pid=os.getpid(), **player.state())
                    else:
                        data = player.command(method, args)
                reply = dict(version=1, id=request['id'], ok=True, data=data)
            except Exception as error:
                code = error.args[0] if isinstance(error, ValueError) and error.args and error.args[0] in {
                    'invalid_request', 'request_too_large', 'invalid_value', 'invalid_speed', 'invalid_volume',
                    'invalid_mute', 'invalid_seek', 'unknown_method', 'media_not_loaded', 'private_media_source_required',
                    'invalid_media_pipe', 'media_state_failed', 'media_seek_failed', 'media_load_failed',
                    'media_pipeline_unavailable', 'media_runtime_init_failed'} else 'media_request_failed'
                reply = dict(version=1, id=request.get('id', '') if isinstance(request, dict) else '', ok=False, error=dict(code=code))
            print(json.dumps(reply, separators=(',', ':')), flush=True)
            if len(line) > 65536:
                break
    finally:
        if player:
            player.close()


if __name__ == '__main__':
    main()
