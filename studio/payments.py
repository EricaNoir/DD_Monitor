"""Direct Bilibili battery payments. Reads may repeat; a payment POST never retries."""
import json
import time
from dataclasses import dataclass
from decimal import Decimal

import requests
from .services import BiliAPI

BASE = 'https://api.live.bilibili.com'


def battery(gold):
    return format(Decimal(int(gold)) / 100, 'f').rstrip('0').rstrip('.') if int(gold) % 100 else str(int(gold) // 100)


def gift_limit(item):
    limit = int(item.get('max_send_limit') or 9999)
    return min(limit, 9999) if limit > 0 else 9999


class PaymentUnknown(ValueError):
    pass


@dataclass(frozen=True)
class Quote:
    kind: str
    room_id: int
    ruid: int
    uid: int
    name: str
    item_id: int
    unit_gold: int
    quantity: int
    text: str = ''
    level: int = 0
    goods_id: int = 12

    @property
    def total(self):
        return self.unit_gold * self.quantity


class PaymentAPI(BiliAPI):
    def identity(self):
        cookies = self.session.cookies.get_dict()
        if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
            raise ValueError('请先在顶部账号按钮扫码登录 B 站。')
        user = self.get('https://api.bilibili.com/x/web-interface/nav')
        if not user.get('isLogin') or not user.get('mid'):
            raise ValueError('登录已过期，请重新扫码登录。')
        return int(user['mid'])

    def room_details(self, rid):
        return self.get(BASE + '/room/v1/Room/get_info', room_id=int(rid))

    def gifts(self, room):
        params = {'room_id': room['room_id'], 'platform': 'pc', 'source': 'live',
                  'area_id': room['area_id'], 'area_parent_id': room['parent_area_id']}
        config = self.get(BASE + '/xlive/web-room/v1/giftPanel/giftConfig', **params)
        panel = self.get(BASE + '/xlive/web-room/v1/giftPanel/giftData', **params)
        by_id = {int(g['id']): g for g in config.get('list', [])}
        discounts = {int(g['gift_id']): int(g['discount_price'])
                     for g in panel.get('discount_gift_list') or []}
        result = []
        for row in (panel.get('room_gift_list') or {}).get('gold_list', []):
            g = by_id.get(int(row['gift_id']))
            scene = row.get('gift_scene') or {}
            if (not g or g.get('coin_type') != 'gold' or int(g.get('price', 0)) <= 0
                    or g.get('gift_type', 0) != 0 or g.get('goods_id') != 15
                    or scene.get('pay_type', 'send_gift') != 'send_gift'):
                continue
            g = dict(g)
            g['price'] = discounts.get(int(g['id']), int(g['price']))
            if g['price'] > 0:
                result.append(g)
        return result

    def sc_config(self, room):
        return self.get(BASE + '/av/v1/SuperChat/config', room_id=room['room_id'],
                        ruid=room['uid'], parent_area_id=room['parent_area_id'], area_id=room['area_id'])

    def wallet(self):
        data = self.get(BASE + '/xlive/revenue/v1/wallet/getStatus', platform='pc')
        gold = data.get('gold')
        if gold is None or not str(gold).isdigit():
            raise ValueError('暂时无法确认电池余额，请刷新后重试。')
        return int(gold)

    def load_panel(self, rid):
        uid = self.identity()
        room = self.room_details(rid)
        gold = self.wallet()
        try:
            gifts, gift_error = self.gifts(room), ''
        except (ValueError, requests.RequestException):
            gifts, gift_error = [], '当前直播间的礼物列表暂不可用。'
        try:
            config, sc_error = self.sc_config(room), ''
        except (ValueError, requests.RequestException):
            config, sc_error = {}, '当前直播间的 SC 配置暂不可用。'
        return {'uid': uid, 'room': room, 'gold': gold, 'gifts': gifts, 'sc': config,
                'sc_error': sc_error, 'gift_error': gift_error}

    def prepare(self, rid, kind, item_id, quantity=1, text=''):
        uid = self.identity()
        room = self.room_details(rid)
        if kind == 'gift':
            item = next((g for g in self.gifts(room) if int(g['id']) == int(item_id)), None)
            if item is None:
                raise ValueError('该礼物已不可用，请刷新礼物列表。')
            if not 1 <= int(quantity) <= gift_limit(item):
                raise ValueError('赠送数量超过该礼物允许的范围。')
            quote = Quote(kind, int(room['room_id']), int(room['uid']), uid, item['name'],
                          int(item_id), int(item['price']), int(quantity))
        elif kind == 'sc':
            config = self.sc_config(room)
            ban = config.get('user_ban_info') or {}
            if ban.get('limited'):
                raise ValueError(ban.get('limited_tip') or '当前账号暂时不能发送 SC。')
            item = next((g for g in config.get('price_configs') or [] if int(g['id']) == int(item_id)), None)
            if item is None or (item.get('type_detail') or {}).get('can_buy') is False:
                raise ValueError('该 SC 档位暂不可购买，请刷新后选择。')
            text = text.strip()
            if not text or len(text.encode('utf-16-le')) // 2 > int(item['limit']):
                raise ValueError(f'请输入 1–{item["limit"]} 字的 SC 内容。')
            amount = Decimal(str(item['price'])) * 1000
            if amount <= 0 or amount != amount.to_integral_value():
                raise ValueError('SC 价格格式无法确认。')
            quote = Quote(kind, int(room['room_id']), int(room['uid']), uid, '醒目留言',
                          int(item_id), int(amount), 1, text, int(item['level']), int(config.get('goods_id') or 12))
        else:
            raise ValueError('不支持的发送类型。')
        if self.wallet() < quote.total:
            raise ValueError(f'电池余额不足，本次需要 {battery(quote.total)} 电池。')
        return quote

    def send(self, quote):
        # Revalidate recipient, identity, eligibility and price after confirmation.
        fresh = self.prepare(quote.room_id, quote.kind, quote.item_id, quote.quantity, quote.text)
        if fresh != quote:
            raise ValueError('价格、账号或礼物配置已变化，请重新确认。')
        if quote.kind == 'gift':
            path = '/xlive/revenue/v2/gift/sendGoldMultiUser'
            data = {'uid': quote.uid, 'gift_id': quote.item_id, 'ruid': quote.ruid,
                    'send_ruid': 0, 'gift_num': quote.quantity, 'coin_type': 'gold', 'bag_id': 0,
                    'platform': 'pc', 'biz_code': 'Live', 'biz_id': quote.room_id,
                    'storm_beat_id': 0, 'price': quote.unit_gold, 'rnd': int(time.time()),
                    'receive_users': json.dumps([{'uid': quote.ruid}]), 'all_flag': 0, 'web_location': '444.8'}
        else:
            path = '/xlive/revenue/v1/order/createOrder'
            data = {'context_id': quote.room_id, 'context_type': 1, 'ruid': quote.ruid,
                    'goods_id': quote.goods_id, 'goods_num': 1, 'pay_gold': quote.total, 'platform': 'pc',
                    'biz_extra': json.dumps({'msg': quote.text, 'level': quote.level, 'trans_key': '',
                                            'biz_id': quote.item_id, 'sc_image_id': 0}, ensure_ascii=False)}
        csrf = self.session.cookies.get_dict()['bili_jct']
        data.update(csrf=csrf, csrf_token=csrf)
        try:
            response = self.session.post(BASE + path, data=data, timeout=(5, 20), allow_redirects=False)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as error:
            raise PaymentUnknown('发送结果未确认，请先核对电池余额和直播间记录；请勿直接重复发送。') from error
        if not isinstance(body, dict) or not isinstance(body.get('code'), int):
            raise PaymentUnknown('服务器返回无法确认，请先核对余额和直播间记录。')
        if body['code'] != 0:
            raise ValueError(f'B 站未确认发送成功：{body.get("message") or body.get("msg") or "请求未通过"} ({body["code"]})')
        result = body.get('data') or {}
        if quote.kind == 'gift':
            return {'text': f'已赠送 {quote.name} × {quote.quantity}', 'order_id': '', 'kind': 'gift'}
        if not isinstance(result, dict) or not result.get('order_id'):
            raise PaymentUnknown('SC 返回未包含订单号，请先核对余额和直播间记录，勿直接重复发送。')
        order = str(result.get('order_id') or '')
        status = result.get('status')
        message = {1: 'SC 订单等待支付，未自动补扣，请先核对余额。',
                   2: 'SC 订单已提交，等待发放或审核。',
                   3: 'SC 订单支付失败，请核对余额。',
                   4: 'SC 订单已提交，等待发放或审核。',
                   5: 'SC 订单已完成，留言显示以 B 站审核结果为准。',
                   6: 'SC 发放失败，请核对退款状态。',
                   7: 'SC 发放失败且未退款，请保留订单号向 B 站客服查询。',
                   8: 'SC 订单正在退款。', 9: 'SC 订单已退款。',
                   10: 'SC 订单退款已取消，请核对余额或联系 B 站客服。',
                   11: 'SC 订单已超时关闭。', 12: 'SC 订单支付失败，请核对余额。'
                   }.get(status, f'SC 订单状态：{status}，请查询结果后再操作。')
        return {'text': message, 'order_id': order, 'kind': 'sc'}

    def sc_result(self, order_id):
        data = self.get(BASE + '/av/v1/SuperChat/getMessage', order_id=order_id)
        status = data.get('status')
        return {0: '留言已显示，等待审核。', 1: '留言正在审核。', 2: '留言已通过审核。',
                3: '留言已移除。', 4: '留言未通过审核。'}.get(status, '暂未查询到明确的留言状态，请稍后再查。')
