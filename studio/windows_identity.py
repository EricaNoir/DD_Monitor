"""Stable taskbar identity and relaunch metadata for a Python-hosted Windows app."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import uuid

APP_ID = 'EricaNoir.DDMonitorStudio'


class GUID(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class PropertyKey(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', ctypes.c_uint32)]


class Value(ctypes.Union):
    _fields_ = [('text', ctypes.c_void_p), ('storage', ctypes.c_byte * 16)]


class PropVariant(ctypes.Structure):
    _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3), ('value', Value)]


def set_process_identity():
    if os.name == 'nt':
        function = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        if function(APP_ID) < 0:
            raise OSError('Could not set Windows app identity')


def relaunch_command(root):
    root = Path(root).resolve()
    launcher = root / 'DD Monitor Studio.exe'
    return subprocess.list2cmdline([str(launcher)] if launcher.is_file()
                                  else [sys.executable, '-B', str(root / 'studio_main.py')])


def set_window_identity(hwnd, root):
    if os.name != 'nt':
        return
    root = Path(root).resolve()
    shell = ctypes.WinDLL('shell32')
    get_store = shell.SHGetPropertyStoreForWindow
    get_store.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    get_store.restype = ctypes.c_long
    iid = GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
    store = ctypes.c_void_p()
    if get_store(int(hwnd), ctypes.byref(iid), ctypes.byref(store)) < 0:
        raise OSError('Could not access taskbar properties')
    write_properties(store, ((2, relaunch_command(root)), (3, str(root / 'favicon.ico') + ',0'),
                             (4, 'DD Monitor Studio'), (5, APP_ID)))


def set_shortcut_identity(path):
    """Attach the same AppID to a shortcut created by the installer."""
    function = ctypes.WinDLL('shell32').SHGetPropertyStoreFromParsingName
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_int,
                         ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    function.restype = ctypes.c_long
    iid = GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
    store = ctypes.c_void_p()
    if function(str(Path(path).resolve()), None, 2, ctypes.byref(iid), ctypes.byref(store)) < 0:
        raise OSError('Could not access shortcut properties')
    write_properties(store, ((5, APP_ID),))


def write_properties(store, values):
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    fmtid = GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3')
    try:
        for pid, text in values:
            buffer = ctypes.create_unicode_buffer(text)
            value = PropVariant()
            value.vt = 31  # VT_LPWSTR; SetValue copies the string.
            value.value.text = ctypes.cast(buffer, ctypes.c_void_p)
            key = PropertyKey(fmtid, pid)
            if set_value(store, ctypes.byref(key), ctypes.byref(value)) < 0:
                raise OSError('Could not set taskbar property')
        if commit(store) < 0:
            raise OSError('Could not commit taskbar properties')
    finally:
        release(store)
