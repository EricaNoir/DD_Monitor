"""Opt-in real DirectSound startup/reconnect check; silent PCM, no network."""
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from studio.runtime import configure_vlc, create_vlc_instance
dll = configure_vlc(ROOT)
import vlc
from PySide6.QtWidgets import QApplication
from studio.player import PlayerTile

app = QApplication([])
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'silence.wav'
    with wave.open(str(path), 'wb') as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(b'\0' * (48000 * 4 * 20))
    instance = create_vlc_instance('--no-video')
    tiles = []
    try:
        # New and recreated outputs must be silent even before Qt can run.
        probe = instance.media_player_new()
        try:
            for cycle in range(3):
                probe.stop()
                media = instance.media_new(str(path))
                probe.set_media(media)
                media.release()
                probe.play()
                deadline = time.monotonic() + 5
                while (probe.get_state() != vlc.State.Playing or probe.audio_get_volume() < 0) and time.monotonic() < deadline:
                    time.sleep(.002)
                assert probe.get_state() == vlc.State.Playing
                assert probe.audio_get_volume() == 0, f'output {cycle} started at volume {probe.audio_get_volume()}'
                probe.audio_set_volume(61)
                probe.audio_set_mute(False)
            print('PASS: 3 recreated native outputs start at volume 0', flush=True)
        finally:
            probe.stop()
            probe.release()

        for index, (volume, muted) in enumerate(((17, False), (42, True), (0, False))):
            tile = PlayerTile(index, instance, {})
            tile.monitor.stop()  # Verify the startup timer, not the 1s fallback.
            tile.volume.setValue(volume)
            tile.set_muted(muted)
            tiles.append(tile)
        for cycle in range(3):
            for tile in tiles:
                tile.clear(emit=False)
                tile.room = {'id': str(tile.index + 1), 'name': 'Silent audio test'}
                tile.got_stream(tile.generation, {'room': tile.room, 'url': str(path)})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                for tile in tiles:
                    volume = tile.player.audio_get_volume()
                    assert volume <= tile.volume.value(), 'startup volume exceeded saved value'
                    if tile.muted:
                        assert volume <= 0 or tile.player.audio_get_mute() == 1, 'muted tile became audible'
                app.processEvents()
                if all(not tile._audio_pending for tile in tiles):
                    break
                time.sleep(.002)
            for tile in tiles:
                assert not tile._audio_pending, 'startup audio did not settle'
                assert not tile.audio_startup.isActive()
                assert tile.player.audio_get_volume() == tile.volume.value()
                assert tile.player.audio_get_mute() == int(tile.muted)
            print(f'PASS: cycle {cycle + 1}, 3 tiles restored independent volume/mute without overshoot', flush=True)
    finally:
        for tile in tiles:
            tile.shutdown()
            tile.close()
        instance.release()
