# DD Monitor Studio

DD Monitor 的交互改版。Windows 原生多屏播放器，增加昵称搜索、可折叠主播库和控制条，以及浏览器式固定弹幕列表。

## 使用

双击 `run-studio.cmd`。首次配置先运行 `setup-studio.ps1`，需要 Windows 64 位和 Python 3.10–3.13。

- 右上角 **添加直播间**，输入 UP 主昵称、房号或直播间链接；支持多选和指定播放位置。
- 左上角固定的侧栏图标或 `Ctrl+B` 展开 / 收起主播库。展开时显示 **UP 主头像和昵称**；收起后保留窄头像栏、悬停昵称和底部「+」添加入口。头像来自 B 站主播资料并在本地缓存，加载失败时显示昵称首字。
- 点击头像定位到已经播放的房间，不会重新加载；尚未播放的主播会在当前画面打开。支持拖入指定画面、本地筛选，以及 1 / 2 / 4 / 6 / 9 画面。
- 顶部「弹幕」或 `Ctrl+J` 控制所有直播间；每个画面右上角另有独立「弹幕」开关。关闭后视频自动扩展，再打开保留该房间的记录和栏宽。「控制条」可独立收起。
- 每个画面可以暂停、静音、调音量、独听、切换画质、重连和放大。**关闭键「×」固定在每个画面的右上角**，隐藏控制条后仍可使用；关闭画面会保留主播库中的收藏。
- 主播标题和播放控制合并在顶部单行，底部不再占用控制条和状态行。悬停主播名或状态点查看直播标题与连接状态；窄画面下，音量、独听、重连和添加入口收进「⋯」菜单。
- 每个直播间旁边都有独立的固定聊天列表，同时展示昵称、粉丝牌、内容和表情；每个房间保留最近 500 条消息。没有横向飘屏动画。新消息在底部追加，可关闭跟随或向上查看历史。
- 拖动各房间的视频与聊天之间的分隔线调整栏宽；顶部「设置」统一调整文字大小、昵称和自动跟随。各聊天栏底部「最新 ↓」返回该房间的最新消息。
- `Ctrl+K` 添加，`Ctrl+B` 主播库，`F11` 全屏，`Esc` 返回。

登录通过 B 站 App 扫码。B 站未登录连接可能返回打码昵称；软件显示服务端实际给出的昵称，不猜测身份。登录和界面配置仅保存到已被 Git 忽略的 `user-data/`。若相邻目录有本人的 `DD-Monitor/app/utils/config.json`，可读取其中已有登录状态。不会修改旧版配置。

这是独立的新界面入口；旧版主程序保留。旧版的录制、翻译、礼物榜等功能暂未迁入 Studio。弹幕区是收到的聊天消息列表，没有模拟浏览器观众榜或送礼入口。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\live_smoke.py
.\.venv\Scripts\python.exe tests\live_ui_smoke.py
.\.venv\Scripts\python.exe tests\tls_smoke.py
.\.venv\Scripts\python.exe tests\avatar_smoke.py
```

第一条离线验证面板开关、宽度/记录保留、设置保存、房间切换、异步过期结果和字号等行为。生成 `.qa/` 下的界面预览，预览使用明确标注的示例聊天。第二条是主动联网的只读验证，检查搜索、真实解码和弹幕接收，不发送消息，不输出登录信息或视频鉴权 URL。

`live_ui_smoke.py` 验证两个真实直播间同时播放、分别显示消息和独立开关。`tls_smoke.py` 验证真实 HTTPS 图片加载。Windows 启动时仅在当前进程内隔离 DLL 搜索路径，Qt 使用 Windows Schannel TLS 后端，避免宿主程序的 OpenSSL DLL 污染；不修改系统 PATH 或关闭证书验证。

`avatar_smoke.py` 验证真实主播头像下载及缓存，并生成展开侧栏和收起头像栏的预览。

## 来源

- 基于 [DD_Monitor_latest](https://gitee.com/zhimingshenjun/DD_Monitor_latest) 的 `47da26d`。该提交虽然有 `DD_Monitor2.17` 标签，但源代码版本号为 2.16，并非保证与发布的 2.17 exe 完全一致。
- 原项目 LGPL 2.1 许可证保留于 `LICENSE`。
- 更新了 [xfgryujk/blivedm](https://github.com/xfgryujk/blivedm/tree/3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6) 的 `clients/web.py` 与 `utils.py`，采用其 WBI 签名和当前房间接口。MIT 归属与许可证保留在 `blivedm/LICENSE`。
- 播放运行库从 [VideoLAN 官方](https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/) 下载，保留其许可证文件；整套 DLL 与插件放在 `runtime/vlc-3.0.21/`，不混用旧版插件。运行库、虚拟环境和用户数据不会提交到仓库。
