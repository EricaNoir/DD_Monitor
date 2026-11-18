"""Network work stays off the Qt UI thread. No credentials are logged."""
import asyncio
import html
import json
import re
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36',
           'Referer': 'https://live.bilibili.com/'}


def plain(value):
    return html.unescape(re.sub(r'<[^>]+>', '', str(value or '')))


def room_number(value):
    value = value.strip()
    if value.isdigit() and int(value) > 0:
        return str(int(value))
    try:
        url = urlparse(value if '://' in value else 'https://' + value)
        if url.hostname == 'live.bilibili.com':
            part = url.path.strip('/').split('/')[0]
            if part.isdigit() and int(part) > 0:
                return str(int(part))
    except ValueError:
        pass
    return None


def safe_image(url):
    if str(url).startswith('//'):
        url = 'https:' + url
    parsed = urlparse(str(url))
    host = parsed.hostname or ''
    if parsed.scheme in ('http', 'https') and (host == 'hdslb.com' or host.endswith('.hdslb.com')):
        return parsed._replace(scheme='https').geturl()
    return ''


class BiliAPI:
    def __init__(self, cookies=None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        for key, value in (cookies or {}).items():
            self.session.cookies.set(key, value, domain='.bilibili.com')

    def get(self, url, **params):
        response = self.session.get(url, params=params, timeout=(5, 12))
        response.raise_for_status()
        body = response.json()
        if body.get('code', 0) != 0:
            raise ValueError(f"B站返回：{body.get('message', body.get('msg', '请求未成功'))} ({body.get('code')})")
        return body.get('data') or {}

    def search(self, query, page=1):
        number = room_number(query)
        if number:
            return {'rooms': [self.room(number)], 'more': False}
        if not self.session.cookies.get_dict().get('buvid3'):
            # The search endpoint requires the normal website visitor cookie.
            self.session.get('https://www.bilibili.com/', timeout=(5, 12)).raise_for_status()
        data = self.get('https://api.bilibili.com/x/web-interface/search/type',
                        search_type='live_user', keyword=query.strip(), page=page)
        rooms = []
        for item in data.get('result') or []:
            rid = item.get('roomid') or item.get('room_id')
            if not rid:
                continue
            rooms.append({'id': str(rid), 'name': plain(item.get('uname')),
                          'title': plain(item.get('title') or item.get('cate_name')),
                          'live': bool(item.get('is_live') or item.get('live_status') == 1),
                          'uid': item.get('uid', 0), 'face': safe_image(item.get('uface') or item.get('face') or '')})
        return {'rooms': rooms, 'more': page < int(data.get('numPages', 1))}

    def room(self, rid):
        info = self.get('https://api.live.bilibili.com/room/v1/Room/get_info', room_id=rid)
        anchor = self.get('https://api.live.bilibili.com/live_user/v1/UserInfo/get_anchor_in_room',
                          roomid=info['room_id']).get('info', {})
        return {'id': str(info['room_id']), 'name': anchor.get('uname') or f"房间 {rid}",
                'title': info.get('title', ''), 'live': info.get('live_status') == 1,
                'uid': info.get('uid', 0), 'face': safe_image(anchor.get('face', ''))}

    def search_with_follow(self, query, page=1):
        result = self.search(query, page)
        return self.with_follow_state(result)

    def with_follow_state(self, result):
        for room in result['rooms']:
            room['following'] = None
        if not self.session.cookies.get_dict().get('SESSDATA'):
            result['follow_state'] = 'login_required'
            return result
        try:
            nav = self.get('https://api.bilibili.com/x/web-interface/nav')
            if not nav.get('isLogin'):
                result['follow_state'] = 'login_required'
                return result
            ids = [str(r['uid']) for r in result['rooms'] if r.get('uid')]
            relations = {}
            for start in range(0, len(ids), 50):
                batch = self.get('https://api.bilibili.com/x/relation/relations', fids=','.join(ids[start:start+50]))
                if not isinstance(batch, dict):
                    raise ValueError('Invalid relation response')
                relations.update(batch)
            for room in result['rooms']:
                relation = relations.get(str(room.get('uid')))
                if isinstance(relation, dict) and isinstance(relation.get('attribute'), int):
                    room['following'] = bool(relation['attribute'] & 3)
            result['follow_state'] = 'ok'
        except (requests.RequestException, ValueError, KeyError, TypeError):
            result['follow_state'] = 'unavailable'
        return result

    def stream(self, rid, quality=400):
        room = self.room(rid)
        if not room['live']:
            return {'room': room, 'url': None}
        data = self.get('https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo',
                        room_id=room['id'], protocol='0,1', format='0,1,2', codec='0', qn=quality,
                        platform='web', ptype=8)
        streams = data.get('playurl_info', {}).get('playurl', {}).get('stream') or []
        candidates = []
        for stream in streams:
            for fmt in stream.get('format', []):
                for codec in fmt.get('codec', []):
                    if codec.get('codec_name') != 'avc':
                        continue
                    for host in codec.get('url_info', []):
                        url = host['host'] + codec['base_url'] + host['extra']
                        score = 0 if fmt.get('format_name') in ('ts', 'fmp4') else 1
                        candidates.append((score, url))
        if not candidates:
            raise ValueError('当前房间未返回可播放视频流，请重新登录或稍后重试。')
        return {'room': room, 'url': sorted(candidates, key=lambda value: value[0])[0][1]}

    def qr(self):
        return self.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate')

    def poll_qr(self, key):
        result = self.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll', qrcode_key=key)
        return {'status': result.get('code'), 'message': result.get('message', ''),
                'cookies': self.session.cookies.get_dict() if result.get('code') == 0 else {}}


class JobSignals(QObject):
    done = Signal(object)
    error = Signal(str)


class Job(QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work = work
        self.signals = JobSignals()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(self.work())
        except requests.Timeout:
            self.signals.error.emit('连接超时，请重试。')
        except requests.RequestException:
            self.signals.error.emit('网络连接失败，请检查网络后重试。')
        except Exception as error:
            self.signals.error.emit(str(error) if isinstance(error, ValueError) else '数据暂时不可用，请重试。')


def parse_chat(command):
    """Use the sender from the actual message, never match by message text."""
    if not command.get('cmd', '').startswith('DANMU_MSG'):
        return None
    info = command.get('info', [])
    if len(info) < 3:
        return None
    user = info[2]
    medal = info[3] if len(info) > 3 else []
    extra = {}
    try:
        extra = json.loads(info[0][15].get('extra', '{}'))
    except (IndexError, TypeError, AttributeError, ValueError):
        pass
    images = {}
    for token, value in (extra.get('emots') or {}).items():
        url = safe_image(value.get('url', ''))
        if url:
            images[token] = url
    emoji = ''
    try:
        emoji = safe_image(info[0][13].get('url', ''))
    except (IndexError, AttributeError, TypeError):
        pass
    return {'name': str(user[1]), 'uid': str(user[0]), 'text': str(info[1]),
            'medal': str(medal[1]) if len(medal) > 1 else '',
            'level': str(medal[0]) if medal else '', 'images': images, 'emoji': emoji}


def parse_activity(command):
    """Normalize real gift/SC events; combo summaries do not count as extra gifts."""
    kind = str(command.get('cmd', '')).split(':')[0]
    data = command.get('data')
    if not isinstance(data, dict):
        return None
    try:
        if kind == 'SUPER_CHAT_MESSAGE_DELETE':
            return {'kind': 'sc_delete', 'ids': [str(i) for i in data.get('ids') or []]}
        if kind == 'SUPER_CHAT_MESSAGE':
            user = data.get('user_info') or {}
            base = (data.get('uinfo') or {}).get('base') or {}
            medal = data.get('medal_info') or {}
            sid = str(data['id'])
            return {'kind': 'sc', 'id': sid, 'event_id': 'sc:' + sid, 'uid': str(data.get('uid', '')),
                    'name': str(base.get('name') or user.get('uname') or (user.get('base') or {}).get('name') or '观众'),
                    'text': str(data.get('message', '')), 'price': str(data.get('price', 0)),
                    'medal': str(medal.get('medal_name', '')), 'level': str(medal.get('medal_level', ''))}
        if kind in ('SEND_GIFT', 'GUARD_BUY'):
            count = int(data.get('num', 0))
            if count <= 0:
                return None
            name = data.get('uname') or data.get('username') or (data.get('uinfo') or {}).get('base', {}).get('name') or '观众'
            gift = data.get('giftName') or data.get('gift_name') or '礼物'
            # rnd can be shared by separate gifts in the same second/session.
            transaction = str(data.get('tid') or '')
            return {'kind': 'gift', 'name': str(name), 'uid': str(data.get('uid', '')),
                    'text': f'赠送 {gift} × {count}', 'gift': str(gift), 'quantity': count,
                    'event_id': f'gift:{data.get("uid", "")}:{transaction}' if transaction else ''}
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    return None


class ChatWorker(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, rid, cookies, parent=None):
        super().__init__(parent)
        self.rid, self.cookies = int(rid), dict(cookies)
        self.stop_requested = threading.Event()

    def stop(self):
        self.stop_requested.set()

    def run(self):
        try:
            asyncio.run(self.listen())
        except Exception:
            if not self.stop_requested.is_set():
                self.status.emit('聊天连接中断，可点击重连')

    async def listen(self):
        import aiohttp
        import blivedm
        from yarl import URL
        owner = self

        class Handler(blivedm.BaseHandler):
            def handle(self, client, command):
                message = parse_activity(command) or parse_chat(command)
                if message:
                    owner.message.emit(message)
                elif command.get('cmd') == '_HEARTBEAT':
                    owner.status.emit('聊天已连接')

        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20), trust_env=True) as session:
            cookies = SimpleCookie()
            for key, value in self.cookies.items():
                cookies[key] = value
                cookies[key]['domain'] = '.bilibili.com'
                cookies[key]['path'] = '/'
            session.cookie_jar.update_cookies(cookies, response_url=URL('https://www.bilibili.com'))
            client = blivedm.BLiveClient(self.rid, session=session)
            client.set_handler(Handler())
            self.status.emit('正在连接聊天…')
            client.start()
            try:
                while not self.stop_requested.is_set() and client.is_running:
                    await asyncio.sleep(.2)
            finally:
                await client.stop_and_close()
