"""Exercise candidate Terminal native code inside the trial probe sandbox."""
import ctypes
from pathlib import Path
import time


# @llr LLR-TERM-MAINT-064
def probe():
    runtime = Path('/opt/zmalacall/current/zmala_terminal/linux')
    for library in ('media/video/libzmala_video.so', 'media/audio/libzmala_speech_audio.so',
                    'turn-runtime/turn-fix.so'):
        ctypes.CDLL(str(runtime/library))
    from zmala_terminal.common.engine import Engine
    engine = Engine({}, lambda *args: None, lambda *args: None, profile='system-update-probe', defer_media=True)
    try:
        for _ in range(10):
            engine.iterate()
            time.sleep(.05)
    finally:
        engine.close()


if __name__ == '__main__':
    probe()
