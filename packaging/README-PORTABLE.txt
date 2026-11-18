DD Monitor Studio Windows 便携版

使用方法
1. 把 ZIP 完整解压到自己可写的文件夹（例如“文档”），不要在压缩包里直接运行。
2. 双击“启动 DD Monitor.cmd”。不需要安装 Git、Python 或 VLC，不需要管理员权限。
3. 左上角扫码登录自己的 B 站账号，再添加 / 收藏直播间。
4. 如果启动失败，用“诊断启动.cmd”查看错误信息。

账号与隐私
发布包不含任何人的登录信息、收藏、聊天记录或配置，也不会自动导入旧版账号。
使用后产生的账号、收藏和日志保存在本目录 user-data 中，不要把使用过的目录直接发给别人。
分享时请发送 GitHub Releases 链接或原始 ZIP。更新时先退出旧版，再把自己的 user-data
复制到新版目录；不要覆盖程序自带的 python 和 runtime 目录。
聊天正文不持久化为历史文件。故障日志可能包含房间信息，分享前请检查。
送礼与 SC 会使用登录账号的电池，仍需在应用内确认发送。

来源与校验
源代码：https://github.com/EricaNoir/DD_Monitor/tree/ui-redesign
下载：https://github.com/EricaNoir/DD_Monitor/releases
fork 来源：https://github.com/zhimingshenjun/DD_Monitor
这是 EricaNoir 的衍生版本，不是 B 站、原作者或 VideoLAN 的官方客户端。
SOURCE.json 记录源码提交和官方运行时来源；MANIFEST.sha256 记录包内每个文件的校验值。
Release 页面另附整个 ZIP 的 SHA256。PowerShell 可运行 Get-FileHash 路径.zip -Algorithm SHA256
进行比对；校验值应从同一官方仓库的 Release 页面获取。
运行时使用 python.org、VideoLAN 官方文件，依赖来自 PyPI，版本和哈希固定。
不会修改系统 PATH、注册开机启动、下载并执行在线更新或要求关闭安全软件。
启动脚本未做商业代码签名，校验和不等于病毒扫描或绝对安全保证；如安全软件报警，
请保留拦截并核对来源，不要关闭防护或随意添加排除项。

许可证
保留项目 LICENSE、blivedm/LICENSE、Python LICENSE.txt、runtime/vlc 内的许可证以及
python/Lib/site-packages 中各依赖的许可证和 .dist-info 元数据。
源代码随包提供，第三方项目来源见 SOURCE.json 和依赖包元数据。
