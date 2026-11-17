# DD Monitor Studio

这是 EricaNoir 维护的 DD 监控室交互与 UI 改版，代码位于 [`ui-redesign`](https://github.com/EricaNoir/DD_Monitor/tree/ui-redesign) 分支。提供多屏直播、独立聊天栏、主播搜索与头像收藏、直播优先排序和紧凑图标工具栏。安装及使用说明见 [README-STUDIO.md](README-STUDIO.md)。

## Fork 来源与致谢

- 原作者：**zhimingshenjun**；原 GitHub 仓库：[zhimingshenjun/DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor)。
- 本改版的源码基线来自原作者的 Gitee 仓库：[DD_Monitor_latest](https://gitee.com/zhimingshenjun/DD_Monitor_latest)，提交 `47da26d`。
- 这是独立维护的衍生改版，并非原作者的官方发布。保留原项目的 [LGPL 2.1 许可证](LICENSE)；第三方组件来源和许可证见 [Studio 来源说明](README-STUDIO.md#来源)。

以下保留原项目说明。

# DD监控室

## 运行指南

确保安装VLC, `HELP.html`内有更多解释。

## 开发指南

推荐在venv/anaconda环境下开发

### 所需包
 - PySide6

 - requests

 - aiowebsocket

 - python-vlc

 - pyinstaller

 - dnspython    

   

   pip安装

   ```bash
   pip install -r requirements.txt
   ```

   

### 打包

在 `scripts` 文件夹下有各平台的打包脚本，需要在仓库根目录运行。

## TODO

### 全平台
 - [X] 加载热播主播时显示加载状态（在Macos上有明显卡顿）

### Windows平台
 - [ ] ?

### MacOS平台
 - [X] 保证程序打包后附带文件可以被访问
 - [ ] 弹幕窗口在启动后不显示
 - [X] 添加热播主播后Thread卡死
 - [ ] ~~添加主播到播放器后不会继承窗口大小，需要重整layout来激活~~ (VLC bug)

### Linux平台
 - [ ] 弹幕窗口在启动后不显示
