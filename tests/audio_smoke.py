"""Opt-in Windows audio-device check using silent PCM, with no network access."""
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.runtime import configure_vlc, create_vlc_instance

dll = configure_vlc(ROOT)
import vlc


def wait_for(check, description):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.05)
    raise AssertionError(description)


with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'silence.wav'
    with wave.open(str(path), 'wb') as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(b'\0' * (48000 * 4 * 60))
    instance = create_vlc_instance('--no-video')
    players = [instance.media_player_new() for _ in range(2)]
    try:
        for player in players:
            media = instance.media_new(str(path))
            player.set_media(media)
            media.release()
            player.play()
        wait_for(lambda: all(p.get_state() == vlc.State.Playing for p in players), 'audio outputs did not start')
        a, b = players
        a.audio_set_volume(23)
        b.audio_set_volume(61)
        for player in players:
            player.audio_set_mute(False)
        wait_for(lambda: [p.audio_get_volume() for p in players] == [23, 61], 'volume is not independent')
        for source, value, expected in [(a, True, [1, 0]), (b, True, [1, 1]),
                                        (a, False, [0, 1]), (b, False, [0, 0])]:
            source.audio_set_mute(value)
            wait_for(lambda: [p.audio_get_mute() for p in players] == expected, 'mute leaked to another player')
            time.sleep(.3)
            assert [p.audio_get_mute() for p in players] == expected
            assert [p.audio_get_volume() for p in players] == [23, 61]
        positions = [p.get_time() for p in players]
        time.sleep(.5)
        assert all(p.get_time() > prior for p, prior in zip(players, positions)), 'audio playback stalled'
        print('PASS: independent mute and volume; both real audio outputs continue playing (silent PCM)')
    finally:
        for player in players:
            player.stop()
            player.release()
        instance.release()
