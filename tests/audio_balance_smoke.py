"""Native VLC filter check; synthesized samples are captured, never played aloud."""
import ctypes
import math
from pathlib import Path
import struct
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_balance(root):
    from studio.runtime import configure_vlc, create_vlc_instance
    from studio.audio_balance import set_player_balance
    configure_vlc(root)
    import vlc
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'levels.wav'
        with wave.open(str(path), 'wb') as sound:
            sound.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            sound.writeframes(b''.join(struct.pack('<hh', *([int(32767 * level * math.sin(i * 2 * math.pi * 440 / 48000))] * 2))
                                       for level in (.03, .5) for i in range(96000)))
        instance = create_vlc_instance()
        player = instance.media_player_new()
        samples = []
        @vlc.CallbackDecorators.AudioPlayCb
        def capture(opaque, buffer, count, pts):
            data = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int16))
            samples.extend(v / 32768 for v in data[:count * 2])
        player.audio_set_callbacks(capture, None, None, None, None, None)
        player.audio_set_format('S16N', 48000, 2)
        media = instance.media_new(str(path))
        player.set_media(media)
        results = []
        try:
            for enabled in (False, True, False):
                samples.clear()
                set_player_balance(player, enabled)
                player.play()
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline and player.get_state() not in (vlc.State.Ended, vlc.State.Error):
                    time.sleep(.02)
                player.stop()
                assert len(samples) >= 372000, 'VLC did not decode the complete test signal'
                rms = lambda data: math.sqrt(sum(v * v for v in data) / len(data))
                results.append((rms(samples[96000:180000]), rms(samples[288000:372000])))
            before, balanced, after = results
            assert balanced[0] > before[0] * 1.3, 'quiet signal did not gain volume'
            assert balanced[1] < before[1] * .6, 'loud signal was not compressed'
            assert balanced[1] / balanced[0] < before[1] / before[0] / 2
            assert all(abs(a - b) < .001 for a, b in zip(before, after)), 'disabling failed to restore original audio'
            gap = lambda values: 20 * math.log10(values[1] / values[0])
            print(f'PASS: native compression reduces loudness gap {gap(before):.1f} -> {gap(balanced):.1f} dB; disable restores original')
        finally:
            player.stop()
            media.release()
            player.release()
            instance.release()


if __name__ == '__main__':
    verify_balance(ROOT)
