"""Select one complete VLC distribution; never mix DLL/plugin versions."""
import os
import sys
from pathlib import Path

_dll_handles = []
_isolated = False
_tls_configured = False


def isolate_process(root):
    """Keep host-app DLLs out of this app. Never change the user's system PATH."""
    global _isolated
    if _isolated or os.name != 'nt':
        return
    import ctypes
    root = Path(root).resolve()
    windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    directories = [Path(sys.executable).parent, Path(sys.base_prefix),
                   Path(sys.base_prefix) / 'DLLs',
                   Path(sys.prefix) / 'Lib/site-packages/PySide6',
                   root / 'runtime/vlc-3.0.21', windows / 'System32', windows]
    directories = list(dict.fromkeys(str(p) for p in directories if p.is_dir()))
    os.environ['PATH'] = os.pathsep.join(directories)
    for key in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'OPENSSL_MODULES', 'OPENSSL_CONF'):
        os.environ.pop(key, None)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetDefaultDllDirectories.argtypes = [ctypes.c_uint32]
    kernel.SetDefaultDllDirectories.restype = ctypes.c_int
    if not kernel.SetDefaultDllDirectories(0x1000):
        raise ctypes.WinError(ctypes.get_last_error())
    for directory in directories:
        _dll_handles.append(os.add_dll_directory(directory))
    _isolated = True


def configure_qt_tls():
    global _tls_configured
    if os.name == 'nt' and not _tls_configured:
        isolate_process(Path(__file__).resolve().parents[1])
        from PySide6.QtNetwork import QSslSocket
        if not QSslSocket.setActiveBackend('schannel'):
            raise RuntimeError('Windows TLS 后端初始化失败，请检查 PySide6 安装。')
        _tls_configured = True


def configure_vlc(root):
    root = Path(root).resolve()
    isolate_process(root)
    runtime = root / 'runtime' / 'vlc-3.0.21'
    if not (runtime / 'libvlc.dll').exists():
        raise RuntimeError('未找到完整 VLC 运行库，请先运行 setup-studio.ps1。')
    os.environ['VLC_PLUGIN_PATH'] = str(runtime / 'plugins')
    os.environ['PYTHON_VLC_MODULE_PATH'] = str(runtime)
    os.environ['PYTHON_VLC_LIB_PATH'] = str(runtime / 'libvlc.dll')
    return os.add_dll_directory(str(runtime)) if os.name == 'nt' else None


def create_vlc_instance(*extra_options):
    import vlc
    # MMDevice shares session volume/mute across this process's players.
    # DirectSound controls each player's own buffer instead.
    return vlc.Instance('--quiet', '--no-video-title-show', '--avcodec-hw=any',
                        '--aout=directsound', '--no-volume-save', *extra_options)
