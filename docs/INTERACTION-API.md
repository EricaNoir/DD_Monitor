# B 站原生送礼与 SC 接口记录

核对日期：2026-11-18。依据 B 站当前直播间公开前端代码、已登录账号的只读接口响应。写入参数采用官方网页的调用方式，但没有为开发验证实际购买礼物或发送 SC；写请求的验证全部使用模拟响应。以下是站内 Web 接口，后续可能变化。

## 来源

- [B 站官方直播间](https://live.bilibili.com/4792266) 当前加载的 [app.9173bc36a11b22ae8196.js](https://s1.hdslb.com/bfs/static/blive/blfe-live-room/static/js/app.9173bc36a11b22ae8196.js)：普通礼物的 `sendGoldMultiUser`、折扣价格解析、礼物目录与钱包查询。
- 同一页面按需加载的 SC 组件 chunk 9203：`SuperChat/config`、`order/createOrder` 和 `SuperChat/getMessage`，包括订单状态与留言审核状态的区分。
- 已登录只读检查：房间信息、礼物配置、房间礼物列表、钱包、SC 档位。实时消息来自已有 `blivedm` WebSocket 客户端。

## 读取

| 接口 | 用途与参数 |
| --- | --- |
| `api.bilibili.com/x/web-interface/nav` | 验证登录并获取付款账号 UID |
| `api.live.bilibili.com/room/v1/Room/get_info` | `room_id` → 真实房号、主播 UID、分区 |
| `/xlive/web-room/v1/giftPanel/giftConfig` | `room_id, platform=pc, source=live, area_id, area_parent_id` → 礼物配置 |
| `/xlive/web-room/v1/giftPanel/giftData` | 同上 → 该房间上架礼物与 `discount_gift_list` |
| `/xlive/revenue/v1/wallet/getStatus` | `platform=pc` → `gold` 余额 |
| `/av/v1/SuperChat/config` | `room_id, ruid, area_id, parent_area_id` → 可购买 SC 档位、字数和账号限制 |
| `/av/v1/SuperChat/getMessage` | `order_id` → 留言及审核状态 |

未注明域名的路径均在 `https://api.live.bilibili.com`。礼物列表取目录和房间上架列表的交集，仅支持 `coin_type=gold, gift_type=0, goods_id=15, pay_type=send_gift`。若有服务端折扣，展示与提交均使用折扣价。

**单位：100 gold = 1 电池；1000 gold = 1 元。** SC 配置的 `price` 以元为单位，创建订单的 `pay_gold` 是 `price × 1000`。不得将 SC 展示金额直接当成电池或 gold 数量。SC 档位和字数上限来自服务端，不写死最低金额；字数按网页 JavaScript 的 UTF-16 长度计算。

## 写入（仅用户确认后）

普通礼物：`POST /xlive/revenue/v2/gift/sendGoldMultiUser`，字段包括 `uid, gift_id, ruid, send_ruid=0, gift_num, coin_type=gold, bag_id=0, platform=pc, biz_code=Live, biz_id=房号, price=当前单价, receive_users=[{"uid":主播UID}], all_flag=0`。

SC：`POST /xlive/revenue/v1/order/createOrder`，字段为 `context_id=房号, context_type=1, ruid, goods_id=配置值或12, goods_num=1, pay_gold, platform=pc`；`biz_extra` JSON 包含 `msg, level, trans_key="", biz_id=档位id, sc_image_id=0`。SC 配置中的展示礼物 `gift_id` 不是订单 `goods_id`。

两者均使用当前用户扫码登录的 Cookie，并附带 `csrf` / `csrf_token=bili_jct`。Cookie 只保留于已忽略的本机用户数据，不上传给第三方服务，不写入日志或仓库。没有 B 币、现金或充值兜底。

发送确认固定房间、主播、付款 UID、数量和金额，提交前重新验证；变化即中止。每次提交仅发送一次 POST，禁止自动重试及重定向。超时等未知结果不能视为失败后重新扣费。SC 的订单状态 2/4 是待发放，5 是订单完成；留言仍有独立审核状态，不将订单提交冒充留言已展示。

## 接收

- `SEND_GIFT`：赠送者、礼物名、数量；使用实际交易 `tid` 去重，不把可能共用的 `rnd` 当交易 ID。
- `SEND_GIFT_V2`：解码 `data.pb` 中 base64 protobuf 的 `SendGiftBroadcast`，展开重复 `gift_list`，逐条显示名称和数量。兼容旧事件名携带 protobuf 及 JSON 礼物批次；同一交易里的不同礼物按礼物 ID 分开去重。赠送者优先使用 `sender_uinfo.base.name`。
- `GUARD_BUY`：显示大航海购买事件，但不提供内置购买入口。
- `SUPER_CHAT_MESSAGE`：金额、赠送者、留言，按 SC ID 去重。支持新 `uinfo.base.name` 和旧 `user_info.uname`。
- `SUPER_CHAT_MESSAGE_DELETE`：移除指定 SC，并阻止该 SC 在当前房间缓存里被重放。
- 不重复插入 `COMBO_SEND` 汇总和日文 SC 副本。

接收范围是连接期间的实时事件，不提供历史礼物账单或开播前的历史 SC 回放。各房间独立保留最近 500 条消息，关掉聊天显示仍继续接收。

新版礼物字段依据上述官方 app 脚本内 `bilibili.live.gift.v1.SendGiftBroadcast`：1=uid、2=uname、10=重复 GiftItem、15=sender_uinfo；GiftItem 的 1=gift_id、2=gift_name、3=num、9=tid。UserInfo 的 1=uid、2=Base；Base 的 1=name。只解析显示所需字段，跳过其他字段；校验长度、类型与 varint 边界，坏包不会中断后续消息。
