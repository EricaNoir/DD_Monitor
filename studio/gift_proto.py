"""Partial SendGiftBroadcast decoder, matching Bilibili's public web schema.

Only reads sender and GiftItem fields. Unknown fields are skipped, not interpreted
as user identities. Bounds are checked before allocating or reading payloads.
"""
import base64

MAX_SIZE = 1024 * 1024


def fields(payload):
    if not isinstance(payload, bytes) or len(payload) > MAX_SIZE:
        raise ValueError('Invalid gift protobuf size')
    pos, result = 0, {}

    def varint():
        nonlocal pos
        value = 0
        for shift in range(0, 70, 7):
            if pos >= len(payload):
                raise ValueError('Truncated gift varint')
            byte = payload[pos]
            pos += 1
            if shift == 63 and byte > 1:
                raise ValueError('Oversized gift varint')
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError('Invalid gift varint')

    while pos < len(payload):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if not 0 < number < 2**29:
            raise ValueError('Invalid protobuf field')
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            length = varint() if wire == 2 else (8 if wire == 1 else 4)
            if length > len(payload) - pos:
                raise ValueError('Truncated gift field')
            value = payload[pos:pos + length]
            pos += length
        else:
            raise ValueError('Unsupported protobuf wire type')
        result.setdefault(number, []).append(value)
    return result


def text_field(values, number):
    value = values.get(number, [b''])[-1]
    if not isinstance(value, bytes):
        raise ValueError('Expected gift text')
    return value.decode('utf-8')


def int_field(values, number):
    value = values.get(number, [0])[-1]
    if not isinstance(value, int):
        raise ValueError('Expected gift number')
    return value


def decode_gift(encoded):
    if not isinstance(encoded, str) or len(encoded) > MAX_SIZE:
        raise ValueError('Invalid encoded gift')
    data = fields(base64.b64decode(encoded, validate=True))
    sender = fields(data.get(15, [b''])[-1])  # user_dagw.UserInfo
    base = fields(sender.get(2, [b''])[-1])  # user_dagw.Base
    uid = int_field(sender, 1) or int_field(data, 1)
    name = text_field(base, 1) or text_field(data, 2) or '观众'
    gifts = []
    for payload in data.get(10, []):  # repeated GiftItem
        item = fields(payload)
        gifts.append({'gift_id': int_field(item, 1), 'gift_name': text_field(item, 2),
                      'num': int_field(item, 3), 'tid': text_field(item, 9)})
    return {'uid': uid, 'uname': name, 'gift_list': gifts}
