"""Opt-in native Windows HWND/taskbar and SC overlay smoke test (sample data)."""
import ctypes
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.runtime import isolate_process
isolate_process(ROOT)
from studio.windows_identity import set_process_identity, set_window_identity, APP_ID, GUID, PropertyKey, PropVariant
set_process_identity()
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from studio.app import StudioWindow
from studio.theme import stylesheet

app = QApplication([])
app.setStyleSheet(stylesheet())
app.setWindowIcon(QIcon(str(ROOT / 'favicon.ico')))
with tempfile.TemporaryDirectory() as folder:
    window = StudioWindow(ROOT, demo=True, state_path=Path(folder) / 'state.json')
    window.resize(1100, 700)
    window.show()
    app.processEvents()
    hwnd = int(window.winId())
    set_window_identity(hwnd, ROOT)
    shell = ctypes.WinDLL('shell32')
    shell.SHGetPropertyStoreForWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    store = ctypes.c_void_p()
    iid = GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
    assert shell.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)) == 0
    table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    get = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant))(table[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
    try:
        for pid, expected in ((5, APP_ID), (2, str(ROOT / 'DD Monitor Studio.exe'))):
            key = PropertyKey(GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), pid)
            value = PropVariant()
            assert get(store, ctypes.byref(key), ctypes.byref(value)) == 0
            assert expected in ctypes.wstring_at(value.value.text)
            ctypes.WinDLL('ole32').PropVariantClear(ctypes.byref(value))
    finally:
        release(store)
    user = ctypes.WinDLL('user32')
    user.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user.GetWindow.restype = ctypes.c_void_p
    for i, tile in enumerate(window.tiles[:4]):
        tile.stack.setCurrentWidget(tile.surface)
        tile.receive_chat(None, {'kind': 'sc', 'id': str(i), 'price': '30', 'name': '本地显示测试',
                                 'text': 'SC 浮层示例，没有发送任何付费消息。'})
    for _ in range(10):
        app.processEvents()
        time.sleep(.03)
    for tile in window.tiles[:4]:
        overlay = tile.sc_overlay
        assert overlay.isVisible()
        assert user.GetWindow(int(overlay.winId()), 4) == hwnd, 'overlay is not owned by main window'
        assert overlay.pos() == tile.stack.mapToGlobal(QPoint(8, 8))
        tile.stack.setCurrentIndex(0)
        tile.stack.setCurrentIndex(1)
    app.processEvents()
    window.resize(1200, 760)
    app.processEvents()
    for tile in window.tiles[:4]:
        tile.sc_overlay.sync()
        assert tile.sc_overlay.isVisible()
        assert tile.sc_overlay.pos() == tile.stack.mapToGlobal(QPoint(8, 8))
    window.tiles[0].sc_overlay.grab().save(str(ROOT / '.qa/sc-native-window.png'))
    window.showMinimized()
    app.processEvents()
    for tile in window.tiles[:4]:
        tile.sc_overlay.sync()
        assert not tile.sc_overlay.isVisible()
    window.showNormal()
    app.processEvents()
    for tile in window.tiles[:4]:
        tile.sc_overlay.sync()
        assert tile.sc_overlay.isVisible()
    window.move(70, 65)
    app.processEvents()
    window.demo = False
    window.save()
    window.demo = True
    expected_size, expected_position = window.size(), window.pos()
    restored = StudioWindow(ROOT, demo=True, state_path=Path(folder) / 'state.json')
    restored.show()
    app.processEvents()
    assert restored.size() == expected_size
    assert (restored.pos() - expected_position).manhattanLength() <= 4
    restored.close()
    window.close()
    app.processEvents()
print('PASS: native AppID/relaunch properties, four owned SC windows, resize/surface recreation/minimize/restore, saved window position and size')
