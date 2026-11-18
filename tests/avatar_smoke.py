"""Opt-in real avatar downloads and fixed rail UI preview."""
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.theme import stylesheet
from studio.runtime import isolate_process
isolate_process(ROOT)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from studio.app import StudioWindow
from studio.services import BiliAPI
from studio.sidebar import AvatarStore
app = QApplication([])
for name in ('msyh.ttc', 'msyhbd.ttc'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
app.setStyle('Fusion')
app.setStyleSheet(stylesheet())
with ThreadPoolExecutor(max_workers=3) as pool:
    rooms = list(pool.map(lambda rid: BiliAPI().room(rid), ['31294374', '4792266', '6524090', '30040584']))
window = StudioWindow(ROOT, demo=True)
window.closed.connect(app.quit)
window.avatars.enabled = True
window.rooms = {r['id']: r for r in rooms}
window.favorites = set(window.rooms)
window.refresh_library()
for tile, room in zip(window.tiles, rooms):
    tile.room = room
    tile.update_title()
    tile.empty_title.setText('直播画面')
    tile.empty_hint.setText('界面预览 · 示例聊天数据')
    tile.empty_add.hide()
    for i in range(9):
        tile.receive_chat(None, {'name': ['一只观众', '山间的风'][i % 2],
                                'text': ['每个房间的消息独立显示', '点击左边头像就能切换'][i % 2]})
window.notice.setText('界面预览 · 真实主播头像，示例聊天数据')
window.show()
window.select_tile(0)
for room in rooms:
    window.avatars.get(room['face'])
output = ROOT / '.qa'
output.mkdir(exist_ok=True)
result = {}
def finish():
    timer.stop()
    result['loaded'] = len(window.avatars.images)
    app.processEvents()
    app.processEvents()
    window.grab().save(str(output / 'avatar-sidebar-collapsed.png'))
    window.open_search(0)
    quick = window.dialogs[-1]
    app.processEvents()
    quick.grab().save(str(output / 'favorites-quick-select.png'))
    quick.close()
    cached = AvatarStore(window.avatars.cache_dir, enabled=False)
    result['cached'] = sum(cached.get(r['face']) is not None for r in rooms)
    print('AVATARS', result, flush=True)
    window.close()
timer = QTimer()
timer.timeout.connect(lambda: finish() if window.avatars.running == 0 and not window.avatars.queue else None)
timer.start(200)
QTimer.singleShot(20000, finish)
app.exec()
assert result.get('loaded') == 4 and result.get('cached') == 4
