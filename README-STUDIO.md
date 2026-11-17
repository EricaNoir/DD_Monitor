# DD Monitor Studio

DD Monitor 的交互改版。Windows 原生多屏播放器，增加昵称搜索、可折叠主播库和控制条，以及浏览器式固定弹幕列表。

## 使用

双击 `run-studio.cmd`。首次配置先运行 `setup-studio.ps1`，需要 Windows 64 位和 Python 3.10–3.13。

- 右上角 **添加直播间**，输入 UP 主昵称、房号或直播间链接；支持多选和指定播放位置。
- **主播库 / 控制条 / 弹幕** 是三个独立开关。关闭弹幕后视频自动扩展，再打开保留聊天记录和面板宽度。`Ctrl+J` 也可以切换弹幕。
- 主播库支持双击播放、拖入指定画面、本地筛选。支持 1 / 2 / 4 / 6 / 9 画面。
- 每个画面可以暂停、静音、调音量、独听、切换画质、重连和放大。
- 固定弹幕面板展示当前选择房间的昵称、粉丝牌、内容和表情；每个房间保留最近 500 条消息。没有横向飘屏动画。新消息在底部追加，可关闭跟随或向上查看历史。
- 拖动面板边缘调整宽度；底部调字号。聊天区右上角「收起」与顶部开关作用相同。
- `Ctrl+K` 添加，`Ctrl+B` 主播库，`F11` 全屏，`Esc` 返回。

登录通过 B 站 App 扫码。B 站未登录连接可能返回打码昵称；软件显示服务端实际给出的昵称，不猜测身份。登录和界面配置仅保存到已被 Git 忽略的 `user-data/`。若相邻目录有本人的 `DD-Monitor/app/utils/config.json`，可读取其中已有登录状态。不会修改旧版配置。

这是独立的新界面入口；旧版主程序保留。旧版的录制、翻译、礼物榜等功能暂未迁入 Studio。弹幕区是收到的聊天消息列表，没有模拟浏览器观众榜或送礼入口。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\live_smoke.py
.\.venv\Scripts\python.exe tests\live_ui_smoke.py
```

第一条离线验证面板开关、宽度/记录保留、设置保存、房间切换、异步过期结果和字号等行为。生成 `.qa/` 下的界面预览，预览使用明确标注的示例聊天。第二条是主动联网的只读验证，检查搜索、真实解码和弹幕接收，不发送消息，不输出登录信息或视频鉴权 URL。

## 来源

- 基于 [DD_Monitor_latest](https://gitee.com/zhimingshenjun/DD_Monitor_latest) 的 `47da26d`。该提交虽然有 `DD_Monitor2.17` 标签，但源代码版本号为 2.16，并非保证与发布的 2.17 exe 完全一致。
- 原项目 LGPL 2.1 许可证保留于 `LICENSE`。
- 更新了 [xfgryujk/blivedm](https://github.com/xfgryujk/blivedm/tree/3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6) 的 `clients/web.py` 与 `utils.py`，采用其 WBI 签名和当前房间接口。MIT 归属与许可证保留在 `blivedm/LICENSE`。
- 播放运行库从 [VideoLAN 官方](https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/) 下载，保留其许可证文件；整套 DLL 与插件放在 `runtime/vlc-3.0.21/`，不混用旧版插件。运行库、虚拟环境和用户数据不会提交到仓库。
