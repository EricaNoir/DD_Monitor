Windows 10/11 x64 便携版：下载 `DD-Monitor-Studio-…-windows-x64.zip`，完整解压后双击 **DD Monitor Studio.exe**。

本次更新：默认开启真正持续调整的动态音量平衡，每个直播间独立测量最近 3 秒电平，缓慢调整增益并保护突发峰值；保留手动音量、静音和独听。正常退出后记住窗口位置、大小和最大化状态。顶部只保留一个刷新按钮，紧跟收藏列表的加号。包含新版多屏图标与原生启动器、横向收藏栏及 SC 浮层修复；旧的 Python 任务栏固定项需取消，再固定新版图标一次。

不需要 Git、Python、VLC 或管理员权限。首次启动没有账号和收藏，请使用自己的 B 站账号扫码登录。

本包由 GitHub Actions 在干净的 Windows 环境中，从对应提交的白名单源码构建。未打包开发者的虚拟环境、登录信息、收藏、日志或本机配置；运行时来自 Python / VideoLAN 官方，PyPI 依赖固定版本和 SHA256。构建执行离线测试、依赖漏洞检查，以及解压后的 Qt 和 VLC 启动验证。

附带 ZIP 的 SHA256 和 GitHub 构建来源证明（artifact attestation），可用于核对下载是否被更改及其构建来源。来源证明与校验值不等于绝对安全保证。应用启动器未做商业代码签名；遇到安全软件拦截时请核对来源，不要关闭防护。

使用后，个人数据只在本目录 `user-data` 内。分享给其他人请转发此 Release 页面或原始 ZIP，不要分享用过的整个文件夹。

本项目 fork 自 [zhimingshenjun/DD_Monitor](https://github.com/zhimingshenjun/DD_Monitor)，是 EricaNoir 的独立衍生版本，并非原作者或 B 站官方客户端。项目、Python、Qt、VLC 和其他依赖的许可证均保留在包内。
