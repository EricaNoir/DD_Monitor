"""Native dynamic balance: two changing sources captured without loudspeakers."""
import ctypes
import math
from pathlib import Path
import struct
import sys
import tempfile
import time
import wave
from array import array

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_balance(root):
    from studio.runtime import configure_vlc, create_vlc_instance
    from studio.audio_balance import set_player_balance, read_player_peak, set_player_gain, LevelController
    configure_vlc(root)
    import vlc
    rate, phase = 48000, 18
    instances, players, media, callbacks, samples = [], [], [], [], []
    controllers = [LevelController(), LevelController()]
    observed = [[], []]
    with tempfile.TemporaryDirectory() as folder:
        try:
            for index, levels in enumerate(((.03, .5), (.5, .03))):
                path = Path(folder) / f'levels-{index}.wav'
                with wave.open(str(path), 'wb') as sound:
                    sound.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
                    for level in levels:
                        second = b''.join(struct.pack('<hh', *([int(32767 * level * math.sin(i * 2 * math.pi * 440 / rate))] * 2)) for i in range(rate))
                        for _ in range(phase):
                            sound.writeframes(second)
                instance = create_vlc_instance()
                instances.append(instance)
                player = instance.media_player_new()
                players.append(player)
                samples.append(array('h'))
                @vlc.CallbackDecorators.AudioPlayCb
                def capture(opaque, buffer, count, pts, target=samples[index]):
                    target.frombytes(ctypes.string_at(buffer, count * 4))
                callbacks.append(capture)
                player.audio_set_callbacks(capture, None, None, None, None, None)
                player.audio_set_format('S16N', rate, 2)
                item = instance.media_new(str(path))
                media.append(item)
                player.set_media(item)
                set_player_balance(player, True)
                player.play()
            deadline = time.monotonic() + 48
            while time.monotonic() < deadline:
                now = time.monotonic()
                for index, player in enumerate(players):
                    if player.get_state() == vlc.State.Playing:
                        gain = controllers[index].update(read_player_peak(player), now)
                        if set_player_gain(player, gain):
                            observed[index].append((player.get_time() / 1000, gain))
                if all(player.get_state() in (vlc.State.Ended, vlc.State.Error) for player in players):
                    break
                time.sleep(.25)
            for player in players:
                player.stop()
            rms = lambda data: math.sqrt(sum((v / 32768) ** 2 for v in data) / len(data))
            results = []
            for end in (phase, phase * 2):
                levels = [rms(data[int((end - 1.5) * rate * 2):int((end - .2) * rate * 2)]) for data in samples]
                assert all(level > 0 for level in levels)
                gap = abs(20 * math.log10(levels[0] / levels[1]))
                results.append(round(gap, 2))
                assert gap < 3, f'Room levels failed to converge: {gap:.1f} dB'
            assert any(t < phase and g > 4 for t, g in observed[0]), 'quiet source never gained volume'
            assert any(t > phase and g < -4 for t, g in observed[0]), 'gain did not react when source became loud'
            assert all(-24 <= g <= 6 for values in observed for _, g in values)
            assert max(abs(v) for data in samples for v in data) < 32767, 'normalization clipped audio'
            player = players[0]
            del samples[0][:]
            set_player_balance(player, False)
            player.play()
            deadline = time.monotonic() + 4
            while len(samples[0]) < rate * 2 and time.monotonic() < deadline:
                time.sleep(.02)
            player.stop()
            original = rms(samples[0][-rate:])
            assert abs(original - .03 / math.sqrt(2)) < .001, 'disable did not restore original signal'
            print(f'PASS: independent live meters; 24.4 dB source gap -> {results} dB after settling; source swap adapts; no clipping; disabling restores PCM')
        finally:
            for player in players:
                player.stop()
                player.release()
            for item in media:
                item.release()
            for instance in instances:
                instance.release()


if __name__ == '__main__':
    verify_balance(ROOT)
