"""Opt-in VLC recovery smoke test: silent local audio, no network or messages."""
import os
import sys
import tempfile
import time
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from studio.runtime import configure_vlc, create_vlc_instance
dll = configure_vlc(ROOT)
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from studio.player import PlayerTile

app = QApplication([])
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'silence.wav'
    with wave.open(str(path), 'wb') as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(b'\0' * (48000 * 4 * 30))
    instance = create_vlc_instance('--no-video')
    tile = PlayerTile(0, instance, {})
    tile.volume.setValue(17)
    tile.set_muted(True)
    room = {'id': '1', 'name': '本地无声重连测试', 'live': True}
    attempts = []
    def fetch(*args):
        attempts.append(time.monotonic())
        print('Stream lookup attempt', len(attempts), flush=True)
        if len(attempts) == 1:
            raise ValueError('模拟网络中断')
        return {'room': dict(room), 'url': str(path)}
    def wait_until(check, timeout=14):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QTest.qWait(50)
            if check():
                return
        raise AssertionError('recovery timed out')
    try:
        with patch('studio.player.BiliAPI.stream', side_effect=fetch), patch.object(tile, 'start_chat'), patch.object(tile.composer, 'set_room'):
            tile.set_room(room)
            wait_until(lambda: len(attempts) == 2 and str(tile.player.get_state()).endswith('Playing')
                       and not tile._audio_pending)
            assert tile.player.audio_get_volume() == 17
            assert tile.player.audio_get_mute()
            tile.player.stop()
            wait_until(lambda: len(attempts) == 3 and str(tile.player.get_state()).endswith('Playing')
                       and not tile._audio_pending)
            assert tile.player.audio_get_volume() == 17
            assert tile.player.audio_get_mute()
            print('PASS: request failure and stopped VLC recover automatically; saved volume/mute preserved')
    finally:
        tile.shutdown()
        tile.close()
        instance.release()
