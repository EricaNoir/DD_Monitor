"""Opt-in read-only network smoke check. Never prints cookies or stream URLs."""
import os
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from studio.runtime import configure_vlc
dll = configure_vlc(ROOT)
from PySide6.QtCore import QCoreApplication, QTimer
from studio.services import BiliAPI, ChatWorker
from studio.state import load_credentials
import vlc

cookies = load_credentials(ROOT)
api = BiliAPI(cookies)
result = api.search('OA-LEAVE7')
print('SEARCH:', len(result['rooms']), 'matches', flush=True)
room = next((r for r in result['rooms'] if r['name'] == 'OA-LEAVE7'), result['rooms'][0])
stream = api.stream(room['id'], 250)
print('ROOM:', stream['room']['name'], 'LIVE:', stream['room']['live'], 'STREAM:', bool(stream['url']), flush=True)
instance = vlc.Instance('--quiet', '--no-video-title-show', '--vout=dummy', '--aout=dummy')
player = instance.media_player_new()
if stream['url']:
    media = instance.media_new(stream['url'])
    media.add_option(':http-user-agent=Mozilla/5.0')
    media.add_option(':http-referrer=https://live.bilibili.com/')
    player.set_media(media)
    player.play()

app = QCoreApplication([])
worker = ChatWorker(room['id'], cookies)
messages = []
worker.message.connect(lambda message: messages.append(message))
worker.status.connect(lambda status: print('CHAT:', status, flush=True))
worker.finished.connect(app.quit)
worker.start()
QTimer.singleShot(25000, worker.stop)
app.exec()
worker.wait(5000)
print('CHAT_MESSAGES:', len(messages), 'WITH_NAMES:', sum(bool(m['name']) for m in messages), flush=True)
if stream['url']:
    stats = vlc.MediaStats()
    media.get_stats(stats)
    print('PLAYBACK:', player.get_state(), 'DECODED_FRAMES:', stats.decoded_video, flush=True)
    media.release()
player.stop()
player.release()
instance.release()
if stream['url'] and stats.decoded_video == 0:
    raise SystemExit('FAIL: live stream did not decode any video frames')
if not messages:
    raise SystemExit('FAIL: no chat messages received during this smoke check')
