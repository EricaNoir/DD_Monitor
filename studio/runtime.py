"""Select one complete VLC distribution; never mix DLL/plugin versions."""
import os
from pathlib import Path


def configure_vlc(root):
    root = Path(root).resolve()
    runtime = root / 'runtime' / 'vlc-3.0.21'
    if not (runtime / 'libvlc.dll').exists():
        raise RuntimeError('未找到完整 VLC 运行库，请先运行 setup-studio.ps1。')
    os.environ['VLC_PLUGIN_PATH'] = str(runtime / 'plugins')
    os.environ['PYTHON_VLC_MODULE_PATH'] = str(runtime)
    os.environ['PYTHON_VLC_LIB_PATH'] = str(runtime / 'libvlc.dll')
    return os.add_dll_directory(str(runtime)) if os.name == 'nt' else None
