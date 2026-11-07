"""Actual shared terminal Engine/HTTP client, with synthetic camera/audio hardware.

Commands are loopback-only and dispatched on the SDK-owning thread. Docker exec
is the lab control channel; it cannot provide a shortcut for SIP/media traffic.
"""
import ctypes as C
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import queue
import struct
import sys
import threading
import time
import wave

from PIL import Image, ImageDraw
from zmala_terminal.common.configuration import Configuration
from zmala_terminal.common import engine as implementation
from zmala_terminal.linux import media
from zmala_terminal.common.native_runtime import library

IDENTITY = sys.argv[1]
COMMANDS = queue.Queue()
EVENTS = []
PENDING = []


class SyntheticBackend:
    CODECS = {'H264'}
    DISPLAY_FILTER = b'MSGLXVideo'
    @staticmethod
    def configure(resources, dll, core, fps, framing):
        media.configure(resources, dll, core, fps, framing)
        # WSL has no Pi V4L2 encoder. Keep the production decoder, but encode
        # synthetic frames with the SDK's OpenH264 software filter.
        factory = dll.linphone_core_get_ms_factory(core)
        enable = library('mediastreamer2').ms_factory_enable_filter_from_name
        enable.argtypes, enable.restype = [C.c_void_p, C.c_char_p, C.c_int], C.c_int
        enable(factory, b'ZmalaV4L2H264Enc', 0)
        enable(factory, b'MSOpenH264Enc', 1)
    poll_video = staticmethod(lambda engine, now, next_probe=0: next_probe)
    received_frame = staticmethod(media.received_frame)
    apply_speaker_volume = staticmethod(lambda engine: None)
    sync_speaker_mute = staticmethod(lambda engine, previous=None: previous)
    codec_stats = staticmethod(media.codec_stats)
    refresh_usb_devices = staticmethod(lambda engine: None)
    filter_devices = staticmethod(lambda devices: devices)
    select_settings = staticmethod(lambda engine, requested: {})


implementation.media_backend = lambda: SyntheticBackend


def api(engine, name, result, types, *args):
    function = getattr(engine.dll, 'linphone_' + name)
    function.restype, function.argtypes = result, types
    return function(*args)


class SyntheticEngine(implementation.Engine):
    def apply_settings(self, settings):
        # Preserve actual protocol/codec configuration; substitute only the devices.
        devices = super().devices()
        cameras = devices['camera']
        camera = next((name for name in cameras if name.startswith('Mire:')),
                      next((name for name in cameras if name.startswith('StaticImage:')), None))
        if not camera:
            raise RuntimeError('SDK has no synthetic camera: ' + repr(cameras))
        if self.core_set_video_device(self.core, camera.encode()):
            raise RuntimeError('Could not select synthetic camera')
        api(self, 'core_set_static_picture', None, [C.c_void_p, C.c_char_p], self.core, b'/tmp/picture.jpg')
        api(self, 'core_set_static_picture_fps', None, [C.c_void_p, C.c_float], self.core, 15.0)
        api(self, 'core_set_use_files', None, [C.c_void_p, C.c_int], self.core, 1)
        api(self, 'core_set_play_file', None, [C.c_void_p, C.c_char_p], self.core, b'/tmp/tone.wav')
        self.core_enable_echo_cancellation(self.core, 0)  # Files have no acoustic feedback path.

    def devices(self):
        return {'camera': ['synthetic'], 'microphone': ['generated tone'], 'speaker': ['WAV capture']}


def call_event(call, state, user, domain):
    EVENTS.append({'state': state, 'peer': user, 'time': round(time.monotonic(), 3)})
    del EVENTS[:-100]
    if state == 1:
        PENDING.append(('answer', call))
    elif state in (13, 14, 19):
        PENDING.append(('release', call))


def generate_media():
    image = Image.new('RGB', (640, 480), '#205080' if IDENTITY == 'a' else '#803050')
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 40):
        draw.rectangle((x, 0, x+15, 479), fill='white')
    draw.text((20, 20), 'Synthetic terminal ' + IDENTITY, fill='black')
    image.save('/tmp/picture.jpg')
    frequency = 440 if IDENTITY == 'a' else 880
    samples = b''.join(struct.pack('<h', int(6000 * math.sin(2*math.pi*frequency*i/16000))) for i in range(16000))
    with wave.open('/tmp/tone.wav', 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        for _ in range(600):
            audio.writeframesraw(samples)


class Control(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        reply = queue.Queue()
        COMMANDS.put((payload, reply))
        try:
            value = reply.get(timeout=15)
        except queue.Empty:
            value = {'error': 'SDK command timed out'}
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    generate_media()
    credentials = json.loads(Path(f'/lab/{IDENTITY}.json').read_text())
    bootstrap = {'server_url': 'http://10.231.100.13:8080', 'device_id': IDENTITY,
                 'device_token': credentials['token']}
    if os.environ.get('ZMALA_LAB_TLS') == '1':
        bootstrap['server_url'] = 'https://10.231.100.15:443'
    configuration = Configuration(bootstrap, Path('/tmp/config-cache.json'))
    for attempt in range(30):
        try:
            config = configuration.fetch()
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    engine = SyntheticEngine(config, call_event, lambda registered: None, profile='network-lab')
    server = ThreadingHTTPServer(('127.0.0.1', 9090), Control)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    record = 0
    try:
        while True:
            engine.iterate()
            video_active = engine.incoming_video_active()
            while PENDING:
                action, call = PENDING.pop(0)
                if action == 'answer':
                    engine.hold_call(call)
                    engine.answer()
                elif engine.call == call:
                    engine.hold_call(None)
            try:
                request, reply = COMMANDS.get_nowait()
            except queue.Empty:
                time.sleep(.01)
                continue
            try:
                action = request['action']
                if action == 'dial':
                    engine.dial(f"sip:{request['peer']}@10.231.100.13")
                elif action == 'end':
                    engine.end()
                elif action == 'record':
                    record += 1
                    path = f'/tmp/received-{record}.wav'
                    # The SDK can append to an existing WAV after a process restart.
                    # Never let audio from an earlier call satisfy a later assertion.
                    Path(path).unlink(missing_ok=True)
                    api(engine, 'core_set_record_file', None, [C.c_void_p, C.c_char_p], engine.core, path.encode())
                elif action == 'fetch':
                    fresh = configuration.fetch(persist=False)
                    reply.put({'device_id': fresh['device_id'], 'server_host': fresh['server_host']})
                    continue
                elif action == 'keyframe':
                    if engine.call:
                        api(engine, 'call_send_vfu_request', None, [C.c_void_p], engine.call)
                elif action == 'status':
                    pass
                else:
                    raise ValueError('Unknown command')
                from tls_client import status as security_status
                reply.put({'registered': engine.registered, 'state': engine.call_get_state(engine.call) if engine.call else 0,
                           'media': engine.media_stats(), 'video_active': video_active,
                           'security': security_status(engine) if os.environ.get('ZMALA_LAB_TLS') == '1' else {},
                           'events': list(EVENTS), 'record': record})
            except Exception as error:
                reply.put({'error': str(error)})
    finally:
        engine.close()
        configuration.deactivate()


if __name__ == '__main__':
    main()
