"""Local diagnostic: print format/status only, never signed URLs."""
import os
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from studio.runtime import configure_vlc
dll = configure_vlc(ROOT)
from studio.services import BiliAPI
from studio.state import load_credentials
import vlc
print('VLC', vlc.libvlc_get_version(), flush=True)
api = BiliAPI(load_credentials(ROOT))
data = api.get('https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo',
               room_id=31294374, protocol='0,1', format='0,1,2', codec=0, qn=250, platform='web')
instance = vlc.Instance('--quiet', '--vout=dummy', '--aout=dummy')
for stream in data['playurl_info']['playurl']['stream']:
    for fmt in stream['format']:
        for codec in fmt['codec']:
            host = codec['url_info'][0]
            url = host['host'] + codec['base_url'] + host['extra']
            with api.session.get(url, timeout=12, stream=True) as response:
                print('FORMAT', fmt['format_name'], codec['codec_name'], 'HTTP', response.status_code,
                      'CONTENT', response.headers.get('Content-Type'), 'PREFIX', repr(next(response.iter_content(20), b'')), flush=True)
            player = instance.media_player_new()
            media = instance.media_new(url)
            media.add_option(':http-user-agent=Mozilla/5.0')
            media.add_option(':http-referrer=https://live.bilibili.com/')
            player.set_media(media)
            player.play()
            time.sleep(8)
            stats = vlc.MediaStats()
            media.get_stats(stats)
            print('STATE', player.get_state(), 'READ', stats.read_bytes, 'FRAMES', stats.decoded_video, flush=True)
            player.stop()
            player.release()
            media.release()
instance.release()
