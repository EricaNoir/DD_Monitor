"""VLC 3 dynamic-range compression, independently applied to each player.

LibVLC 3 creates an empty player-level audio-filter variable (no inheritance),
so neither instance nor media options enable this filter. Use the bundled
VLC 3 core's typed variable API, with version/export/type checks. No Windows
session volume, PCM callbacks or recurring volume writes are involved.
"""
import ctypes
import os
from pathlib import Path

# Quiet speech gains at most 4 dB; peaks are gently compressed above -24 dBFS.
OPTIONS = ('--compressor-threshold=-24', '--compressor-ratio=4',
           '--compressor-attack=10', '--compressor-release=300',
           '--compressor-knee=6', '--compressor-makeup-gain=4',
           '--compressor-rms-peak=0.2')
_core = None


class VLCValue(ctypes.Union):
    _fields_ = [('integer', ctypes.c_int64), ('text', ctypes.c_char_p)]


def core_api():
    global _core
    if _core is None:
        import vlc
        if os.name != 'nt' or not vlc.libvlc_get_version().startswith(b'3.0.'):
            raise RuntimeError('音量平衡需要随应用提供的 Windows VLC 3 运行库。')
        library = Path(os.environ['PYTHON_VLC_LIB_PATH']).with_name('libvlccore.dll')
        core = ctypes.CDLL(str(library))
        core.var_Type.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        core.var_Type.restype = ctypes.c_int
        core.var_SetChecked.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, VLCValue]
        core.var_SetChecked.restype = ctypes.c_int
        _core = core
    return _core


def set_player_balance(player, enabled):
    core = core_api()
    if core.var_Type(player, b'audio-filter') & 0xf0 != 0x40:
        raise RuntimeError('当前播放器不支持音量平衡。')
    # This app owns the filter chain; it does not enable other audio filters.
    value = VLCValue(text=b'compressor' if enabled else b'')
    if core.var_SetChecked(player, b'audio-filter', 0x40, value) != 0:
        raise RuntimeError('无法切换音量平衡。')
