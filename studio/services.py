"""Network work stays off the Qt UI thread. No credentials are logged."""
import asyncio
import html
import json
import re
import threading
import time
import hashlib
from urllib.parse import urlencode, quote
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import requests
from .gift_proto import decode_gift
from .room_metrics import live_start, audience_update
from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThread, Qt, Signal, Slot

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

    def chat_limit(self, rid):
        if not all(self.session.cookies.get_dict().get(k) for k in ('SESSDATA', 'bili_jct')):
            raise ValueError('请先点击顶部账号图标登录 B 站。')
        data = self.get('https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByUser', room_id=int(rid))
        limit = int(((data.get('property') or {}).get('danmu') or {}).get('length') or 20)
        return max(1, min(limit, 500))

    def send_chat(self, rid, text):
        text = text.strip()
        limit = self.chat_limit(rid)
        if not text or len(text.encode('utf-16-le')) // 2 > limit:
            raise ValueError(f'请输入 1–{limit} 字的弹幕。')
        nav = self.get('https://api.bilibili.com/x/web-interface/nav')
        if not nav.get('isLogin'):
            raise ValueError('登录已过期，请重新扫码。')
        keys = nav.get('wbi_img') or {}
        joined = ''.join(str(keys.get(k, '')).rpartition('/')[2].split('.')[0] for k in ('img_url', 'sub_url'))
        table = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13)
        if len(joined) < 64:
            raise ValueError('暂时无法获取发送签名，请稍后再试。')
        key = ''.join(joined[i] for i in table)
        params = {'web_location': '444.8', 'wts': str(int(time.time()))}
        params['w_rid'] = hashlib.md5((urlencode(sorted(params.items()), quote_via=quote) + key).encode()).hexdigest()
        csrf = self.session.cookies.get_dict()['bili_jct']
        payload = {'msg': text, 'roomid': int(rid), 'color': 16777215, 'fontsize': 25,
                   'mode': 1, 'rnd': int(time.time()), 'bubble': 0, 'dm_type': 0,
                   'csrf': csrf, 'csrf_token': csrf}
        try:
            response = self.session.post('https://api.live.bilibili.com/msg/send', params=params,
                                         data=payload, timeout=(5, 12), allow_redirects=False)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ValueError('发送结果未确认，请核对聊天记录后再试；没有自动重发。') from error
        if not isinstance(body, dict) or not isinstance(body.get('code'), int):
            raise ValueError('发送结果未确认，请核对聊天记录。')
        message = body.get('message') or body.get('msg') or ''
        # This endpoint can return code=0 with a nonempty rejection message.
        if body['code'] != 0 or message not in ('', '0', 'OK', 'ok', 'success'):
            raise ValueError(str(message or 'B 站未接受这条弹幕。'))
        return {'uid': str(nav.get('mid') or ''), 'text': text}

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
                'uid': info.get('uid', 0), 'face': safe_image(anchor.get('face', '')),
                'live_start': live_start(info.get('live_time'))}

    def search_with_follow(self, query, page=1):
        result = self.search(query, page)
        return self.with_follow_state(result)

    def followings(self, query='', page=1):
        if not self.session.cookies.get_dict().get('SESSDATA'):
            raise ValueError('请先登录 B 站，查看自己的关注列表。')
        nav = self.get('https://api.bilibili.com/x/web-interface/nav')
        if not nav.get('isLogin') or not nav.get('mid'):
            raise ValueError('登录已过期，请重新扫码登录。')
        params = {'vmid': nav['mid'], 'pn': page, 'ps': 50}
        path = 'https://api.bilibili.com/x/relation/followings'
        if query.strip():
            path += '/search'
            params['name'] = query.strip()
        else:
            params['order'] = 'desc'
        data = self.get(path, **params)
        accounts = data.get('list') or []
        rooms, unavailable = {}, False
        if accounts:
            try:
                rooms = self.get('https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids',
                                 **{'uids[]': [item['mid'] for item in accounts]})
                if not isinstance(rooms, dict):
                    raise ValueError('Invalid room map')
            except (ValueError, requests.RequestException):
                rooms, unavailable = {}, True
        result = []
        for account in accounts:
            info = rooms.get(str(account['mid'])) or {}
            rid = info.get('room_id') or 0
            result.append({'id': str(rid) if int(rid) > 0 else '', 'uid': account['mid'],
                           'name': plain(account.get('uname')), 'face': safe_image(account.get('face', '')),
                           'title': plain(info.get('title')), 'live': info.get('live_status') == 1,
                           'following': True, 'room_known': not unavailable})
        total = int(data.get('total') or 0)
        return {'rooms': result, 'total': total, 'more': bool(accounts) and page * 50 < total,
                'follow_state': 'ok', 'rooms_unavailable': unavailable}

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

    def room_statuses(self, rooms):
        updated = []
        known = []
        for room in rooms:
            if room.get('uid'):
                known.append(room)
            else:
                updated.append(dict(self.room(room['id']), id=room['id']))
        for offset in range(0, len(known), 50):
            batch = known[offset:offset + 50]
            data = self.get('https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids',
                            **{'uids[]': [room['uid'] for room in batch]})
            for room in batch:
                info = data.get(str(room['uid']))
                if not info or 'live_status' not in info:
                    continue
                updated.append(dict(room, live=info['live_status'] == 1,
                                    live_start=live_start(info.get('live_time')),
                                    title=plain(info.get('title', room.get('title', ''))),
                                    name=plain(info.get('uname') or room['name']),
                                    face=safe_image(info.get('face')) or room.get('face', '')))
        return updated

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
    completed = Signal(bool, object)

    def __init__(self, owner=None):
        # A runnable is auto-deleted on a pool thread. Keep its dispatcher alive
        # independently until the GUI has consumed the result, even if the
        # requesting widget is destroyed while the network call is in flight.
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError('Create UI jobs on the application thread')
        super().__init__(app)
        self.active = True
        self.completed.connect(self.deliver, Qt.QueuedConnection)
        if owner is not None:
            owner.destroyed.connect(self.cancel)

    @Slot()
    def cancel(self):
        self.active = False

    @Slot(bool, object)
    def deliver(self, success, result):
        try:
            if self.active:
                if success:
                    self.done.emit(result)
                else:
                    self.error.emit(result)
        finally:
            self.deleteLater()


class Job(QRunnable):
    def __init__(self, work, owner=None):
        super().__init__()
        self.work = work
        self.signals = JobSignals(owner)

    @Slot()
    def run(self):
        try:
            result = self.work()
        except requests.Timeout:
            success, result = False, '连接超时，请重试。'
        except requests.RequestException:
            success, result = False, '网络连接失败，请检查网络后重试。'
        except Exception as error:
            success = False
            result = str(error) if isinstance(error, ValueError) else '数据暂时不可用，请重试。'
        else:
            success = True
        self.signals.completed.emit(success, result)


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
                    'start_time': data.get('start_time', 0), 'end_time': data.get('end_time', 0),
                    'duration': data.get('time', 0),
                    'medal': str(medal.get('medal_name', '')), 'level': str(medal.get('medal_level', ''))}
        if kind in ('SEND_GIFT', 'GUARD_BUY'):
            count = int(data.get('num', 0))
            if count <= 0:
                return None
            sender = data.get('sender_uinfo') or data.get('uinfo') or {}
            name = (sender.get('base') or {}).get('name') or data.get('uname') or data.get('username') or '观众'
            uid = str(sender.get('uid') or data.get('uid', ''))
            gift = data.get('giftName') or data.get('gift_name') or '礼物'
            gift_id = str(data.get('giftId') or data.get('gift_id') or '')
            # rnd can be shared by separate gifts in the same second/session.
            transaction = str(data.get('tid') or '')
            return {'kind': 'gift', 'name': str(name), 'uid': uid,
                    'text': f'赠送 {gift} × {count}', 'gift': str(gift), 'quantity': count,
                    'event_id': f'gift:{uid}:{transaction}:{gift_id}' if transaction else ''}
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    return None


def parse_messages(command):
    """One V2 broadcast may contain multiple gifts, each with its own count/ID."""
    kind = str(command.get('cmd', '')).split(':')[0]
    data = command.get('data')
    if kind in ('SEND_GIFT', 'SEND_GIFT_V2') and isinstance(data, dict):
        try:
            if data.get('pb'):
                data = decode_gift(data['pb'])
            if 'gift_list' in data:
                result = []
                for item in data['gift_list']:
                    # Sender belongs to the broadcast, not the receiving GiftItem.
                    merged = dict(item, uid=data.get('uid', ''), uname=data.get('uname', ''),
                                  sender_uinfo=data.get('sender_uinfo') or {})
                    message = parse_activity({'cmd': 'SEND_GIFT', 'data': merged})
                    if message:
                        result.append(message)
                return result
            command = dict(command, cmd='SEND_GIFT', data=data)
        except (ValueError, TypeError, KeyError, AttributeError):
            return []
    message = parse_activity(command) or parse_chat(command)
    return [message] if message else []


class ChatWorker(QThread):
    message = Signal(dict)
    status = Signal(str)
    audience = Signal(dict)

    def __init__(self, rid, cookies, parent=None):
        super().__init__(parent)
        self.rid, self.cookies = int(rid), dict(cookies)
        self.stop_requested = threading.Event()

    def stop(self):
        self.stop_requested.set()

    def run(self):
        attempts = 0
        while not self.stop_requested.is_set():
            try:
                asyncio.run(self.listen())
            except Exception:
                pass
            if self.stop_requested.is_set():
                return
            delay = min(30, 3 * 2 ** min(attempts, 4))
            attempts += 1
            self.status.emit(f'聊天连接中断，{delay} 秒后自动重连')
            if self.stop_requested.wait(delay):
                return

    async def load_active_sc(self, session):
        try:
            async with session.get('https://api.live.bilibili.com/av/v1/SuperChat/getMessageList',
                                   params={'room_id': self.rid}) as response:
                if response.status != 200:
                    return
                body = await response.json()
            if body.get('code') != 0:
                return
            for data in (body.get('data') or {}).get('list') or []:
                if float(data.get('end_time') or 0) > time.time() and not self.stop_requested.is_set():
                    message = parse_activity({'cmd': 'SUPER_CHAT_MESSAGE', 'data': data})
                    if message:
                        message['historical'] = True
                        self.message.emit(message)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, asyncio.TimeoutError):
            pass  # A failed preload must not interrupt the live socket.

    async def listen(self):
        import aiohttp
        import blivedm
        from yarl import URL
        owner = self

        class Handler(blivedm.BaseHandler):
            def handle(self, client, command):
                audience = audience_update(command)
                if audience is not None:
                    owner.audience.emit(audience)
                for message in parse_messages(command):
                    owner.message.emit(message)
                if command.get('cmd') == '_HEARTBEAT':
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
            active_sc = asyncio.create_task(self.load_active_sc(session))
            try:
                while not self.stop_requested.is_set() and client.is_running:
                    await asyncio.sleep(.2)
            finally:
                active_sc.cancel()
                await asyncio.gather(active_sc, return_exceptions=True)
                await client.stop_and_close()
