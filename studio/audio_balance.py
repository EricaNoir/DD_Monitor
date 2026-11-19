"""VLC 3 per-player metering and smooth dynamic level correction.

LibVLC 3 creates an empty player-level audio-filter variable (no inheritance),
so neither instance nor media options enable this filter. Use the bundled
VLC 3 core's typed variable API, with version/export/type checks. No Windows
session volume, PCM callbacks or recurring volume writes are involved.
"""
import ctypes
import os
import math
from collections import deque
from pathlib import Path

# Meter the original source, apply smooth flat gain, then catch transient peaks.
# VLC's flat equalizer has a fixed 0.25 input factor; compensate explicitly.
FLAT_PREAMP = 20 * math.log10(4)
OPTIONS = ('--compressor-threshold=-6', '--compressor-ratio=12',
           '--compressor-attack=1.5', '--compressor-release=150',
           '--compressor-knee=1', '--compressor-makeup-gain=0',
           '--compressor-rms-peak=1', '--no-equalizer-2pass',
           '--audiobargraph_a-silence=0', '--audiobargraph_a-bargraph_repetition=2')
_core = None


class VLCValue(ctypes.Union):
    _fields_ = [('integer', ctypes.c_int64), ('text', ctypes.c_char_p),
                ('pointer', ctypes.c_void_p), ('number', ctypes.c_float)]


class VLCList(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_int), ('count', ctypes.c_int),
                ('values', ctypes.POINTER(VLCValue))]


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
        core.var_Inherit.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(VLCValue)]
        core.var_Inherit.restype = ctypes.c_int
        core.vlc_list_children.argtypes = [ctypes.c_void_p]
        core.vlc_list_children.restype = ctypes.POINTER(VLCList)
        core.vlc_list_release.argtypes = [ctypes.POINTER(VLCList)]
        core.vlc_list_release.restype = None
        _core = core
    return _core


def set_player_balance(player, enabled):
    core = core_api()
    if core.var_Type(player, b'audio-filter') & 0xf0 != 0x40:
        raise RuntimeError('当前播放器不支持音量平衡。')
    # This app owns the filter chain; it does not enable other audio filters.
    if enabled:
        for key, kind, value in ((b'equalizer-preamp', 0x50, VLCValue(number=FLAT_PREAMP)),
                                 (b'equalizer-bands', 0x40, VLCValue(text=b'0 0 0 0 0 0 0 0 0 0'))):
            if core.var_SetChecked(player, key, kind, value) != 0:
                raise RuntimeError('无法初始化动态增益。')
    value = VLCValue(text=b'audiobargraph_a:equalizer:compressor' if enabled else b'')
    if core.var_SetChecked(player, b'audio-filter', 0x40, value) != 0:
        raise RuntimeError('无法切换音量平衡。')


def read_player_peak(player):
    """Read native per-buffer channel peaks, not system/session volume.

    The bargraph variable belongs to a VLC instance, so the app must use one
    instance per tile. This is a short-window level estimate, not LUFS/RMS.
    """
    import vlc
    value = VLCValue()
    if core_api().var_Inherit(player, b'audiobargraph_v-i_values', 0x40, ctypes.byref(value)) != 0:
        return None
    if not value.pointer:
        return None
    try:
        levels = [float(v) for v in ctypes.string_at(value.pointer).split(b':') if v]
        return max(levels) if levels and all(math.isfinite(v) and v >= 0 for v in levels) else None
    except ValueError:
        return None
    finally:
        vlc.libvlc_free(value.pointer)


def set_player_gain(player, gain_db):
    """Update flat preamp through its audio-output callback without reopening.

    Hold the native child list while looking up the output. Never retain an
    output pointer across reconnects, and never access VLC struct internals.
    """
    gain_db = max(-24.0, min(6.0, float(gain_db)))
    core = core_api()
    children = core.vlc_list_children(player)
    if not children:
        return False
    try:
        for index in range(children.contents.count):
            child = children.contents.values[index].pointer
            if core.var_Type(child, b'equalizer-preamp') & 0xf0 == 0x50:
                return core.var_SetChecked(child, b'equalizer-preamp', 0x50,
                                           VLCValue(number=FLAT_PREAMP + gain_db)) == 0
        return False
    finally:
        core.vlc_list_release(children)


class LevelController:
    """Smooth automatic gain to a common -24 dBFS short-window peak level.

    Energy-average sampled buffer peaks over 3 seconds; wait for 2 seconds of
    active audio before learning. Ignore < -48 dBFS (silence/noise), limit gain
    to -24/+6 dB, and use asymmetric 6/2 dB-per-second down/up slew rates.
    Manual volume is downstream and never fed into this controller.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.samples = deque()
        self.gain_db = 0.0
        self.updated = None
        self.silence_since = None

    def update(self, peak, now):
        dt = min(.5, max(0.0, now - self.updated)) if self.updated is not None else 0.0
        self.updated = now
        while self.samples and now - self.samples[0][0] > 3:
            self.samples.popleft()
        if peak is None or not math.isfinite(peak) or peak < 0:
            self.samples.clear()
            return self.gain_db
        # The meter is upstream of the gain and limiter: no feedback or
        # compensation for delayed decoder/output buffers is necessary.
        source = peak
        if source < 10 ** (-48 / 20):
            self.silence_since = now if self.silence_since is None else self.silence_since
            if now - self.silence_since >= 3:
                self.samples.clear()
                self.gain_db += max(-dt, min(dt, -self.gain_db))
            return self.gain_db
        self.silence_since = None
        self.samples.append((now, source * source))
        while self.samples and now - self.samples[0][0] > 3:
            self.samples.popleft()
        if now - self.samples[0][0] < 2:
            return self.gain_db
        level_db = 10 * math.log10(sum(value for _, value in self.samples) / len(self.samples))
        desired = max(-24.0, min(6.0, -24.0 - level_db))
        # A small deadband avoids needless filter writes around the target.
        difference = desired - self.gain_db
        if abs(difference) >= .2:
            self.gain_db += max(-6 * dt, min(2 * dt, difference))
        return self.gain_db
