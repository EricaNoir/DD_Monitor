"""Wire fixtures follow official SendGiftBroadcast/GiftItem field numbers."""
import base64
import unittest
from studio.services import parse_messages


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def number(field, value):
    return varint(field << 3) + varint(value)


def blob(field, value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return varint((field << 3) | 2) + varint(len(value)) + value


def broadcast(items=None):
    items = items or [(7, '小花花', 3), (8, '赞', 2)]
    sender = number(1, 123456789012) + blob(2, blob(1, '示例赠送者'))
    payload = blob(15, sender) + number(11, 1)
    for gid, name, count in items:
        item = number(1, gid) + blob(2, name) + number(3, count) + blob(9, 'transaction-1')
        # An unrelated fixed32 animation parameter must not break the decoder.
        item += varint((16 << 3) | 5) + b'\x00\x00\x80\x3f'
        payload += blob(10, item)
    return base64.b64encode(payload).decode('ascii')


class GiftProtocolTests(unittest.TestCase):
    def test_v2_protobuf_expands_every_gift_and_keeps_sender(self):
        result = parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': broadcast()}})
        self.assertEqual([(m['gift'], m['quantity']) for m in result], [('小花花', 3), ('赞', 2)])
        self.assertTrue(all(m['name'] == '示例赠送者' and m['uid'] == '123456789012' for m in result))
        self.assertNotEqual(result[0]['event_id'], result[1]['event_id'])

    def test_old_and_new_format_have_same_transaction_identity(self):
        old = parse_messages({'cmd': 'SEND_GIFT', 'data': {'sender_uinfo': {'uid': 123456789012,
                'base': {'name': '示例赠送者'}}, 'giftId': 7, 'giftName': '小花花', 'num': 3, 'tid': 'transaction-1'}})[0]
        new = parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': broadcast()}})[0]
        self.assertEqual(old, new)

    def test_protobuf_also_accepted_on_legacy_command(self):
        self.assertEqual(len(parse_messages({'cmd': 'SEND_GIFT:1', 'data': {'pb': broadcast()}})), 2)

    def test_json_batch_and_v2_plain_json(self):
        batch = {'uid': 99, 'uname': '赠送者', 'gift_list': [
            {'gift_id': 2, 'gift_name': '花', 'num': 1}, {'gift_id': 3, 'gift_name': '心', 'num': 2}]}
        messages = parse_messages({'cmd': 'SEND_GIFT_V2', 'data': batch})
        self.assertEqual([m['quantity'] for m in messages], [1, 2])
        self.assertEqual(messages[1]['name'], '赠送者')
        self.assertEqual(len(parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'num': 1, 'uname': '甲', 'gift_name': '花'}})), 1)

    def test_legacy_sender_fallback(self):
        payload = number(1, 42) + blob(2, '旧字段昵称') + blob(10, number(1, 7) + blob(2, '花') + number(3, 1))
        result = parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': base64.b64encode(payload).decode()}})
        self.assertEqual((result[0]['uid'], result[0]['name']), ('42', '旧字段昵称'))

    def test_bad_packets_do_not_interrupt_next_chat(self):
        malformed = ['invalid!', 'x' * (1024 * 1024 + 1)]
        malformed += [base64.b64encode(raw).decode() for raw in (
            b'\x80', b'\x52\xff\xff\x01', b'\x00\x00', b'\x0b', b'\x80' * 11,
            b'\x12\x01\xff', b'\x52\x01\x80')]
        for pb in malformed:
            with self.subTest(pb=pb[:25]):
                self.assertEqual(parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': pb}}), [])
        self.assertEqual(parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': broadcast()}})[0]['quantity'], 3)

    def test_zero_count_and_combo_summary_are_not_extra_gifts(self):
        self.assertEqual(parse_messages({'cmd': 'SEND_GIFT_V2', 'data': {'pb': broadcast([(7, '花', 0)])}}), [])
        self.assertEqual(parse_messages({'cmd': 'COMBO_SEND', 'data': {'num': 3}}), [])


if __name__ == '__main__':
    unittest.main()
