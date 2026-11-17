"""Reproduce inherited host PATH; verify real Qt HTTPS image loading."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.runtime import isolate_process
isolate_process(ROOT)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument
from PySide6.QtNetwork import QSslSocket
from studio.services import BiliAPI, safe_image
from studio.chat import ChatView
app = QApplication([])
view = ChatView()
data = BiliAPI().get('https://api.live.bilibili.com/live_user/v1/UserInfo/get_anchor_in_room', roomid=31294374)
url = safe_image(data['info']['face'])
assert url, 'No test image returned by the official room API'
view.loadResource(QTextDocument.ImageResource, QUrl(url))
timer = QTimer()
timer.timeout.connect(lambda: app.quit() if not view.pending else None)
timer.start(100)
QTimer.singleShot(15000, app.quit)
app.exec()
print('TLS_BACKEND:', QSslSocket.activeBackend(), 'IMAGE_LOADED:', url in view.images,
      'HOST_PATH_REMOVED:', 'poppler' not in os.environ['PATH'].lower(), flush=True)
assert QSslSocket.activeBackend() == 'schannel'
assert url in view.images, 'Qt HTTPS image request failed'
