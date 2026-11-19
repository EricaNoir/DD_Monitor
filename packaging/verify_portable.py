"""Offline smoke test for an extracted portable package; never uses real accounts."""
import os
from pathlib import Path
import tempfile
import time
import wave

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
from studio.runtime import configure_vlc, create_vlc_instance
dll = configure_vlc(ROOT)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from studio.app import StudioWindow
from studio.state import load_credentials
from studio.theme import stylesheet
import requests
import aiohttp
import brotli
import qrcode
import vlc
import blivedm

assert not (ROOT / 'user-data').exists(), 'Package contains user data'
assert load_credentials(ROOT) == {}, 'Package imported an account'
app = QApplication([])
for name in ('msyh.ttc', 'msyhbd.ttc'):
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setStyle('Fusion')
app.setStyleSheet(stylesheet())
with tempfile.TemporaryDirectory() as temp:
    window = StudioWindow(ROOT, demo=True, state_path=Path(temp) / 'studio.json')
    window.show()
    app.processEvents()
    assert window.library.height() == 42
    assert window.library_add.width() == 42
    assert window.refresh_live_button.width() == 32
    assert (ROOT / 'DD Monitor Studio.exe').is_file()
    assert not window.cookies
    window.close()
    sound_path = Path(temp) / 'silence.wav'
    with wave.open(str(sound_path), 'wb') as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(b'\0' * (48000 * 4 * 2))
    instance = create_vlc_instance('--vout=dummy', '--aout=dummy')
    assert instance
    player = instance.media_player_new()
    media = instance.media_new(str(sound_path))
    player.set_media(media)
    media.release()
    player.play()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and player.get_state() != vlc.State.Playing:
        app.processEvents()
        time.sleep(.02)
    assert player.get_state() == vlc.State.Playing, 'Bundled VLC failed to decode local audio'
    player.stop()
    player.release()
    instance.release()
assert not (ROOT / 'user-data').exists(), 'Self-check created private data in package'
import runpy
runpy.run_path(str(ROOT / 'tests/audio_balance_smoke.py'))['verify_balance'](ROOT)
print('PASS: clean account, bundled imports, Qt UI, Windows TLS initialization and VLC decode')
