"""Render the editable vector master to Windows multi-resolution icon assets."""
from pathlib import Path
import io
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
renderer = QSvgRenderer(str(ROOT / 'assets/studio-icon.svg'))
assert renderer.isValid()
canvas = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
canvas.fill(Qt.transparent)
painter = QPainter(canvas)
renderer.render(painter)
painter.end()
canvas.save(str(ROOT / 'assets/studio-icon.png'))
data = QByteArray()
buffer = QBuffer(data)
buffer.open(QIODevice.WriteOnly)
canvas.save(buffer, 'PNG')
image = Image.open(io.BytesIO(bytes(data)))
image.save(ROOT / 'favicon.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
