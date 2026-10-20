import os, sys
for p in (r"C:\Users\doxuanhop\AppData\Local\Programs\Python\Python311\python.exe",
          r"C:\Users\doxuanhop\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe"):
    print(p, os.path.exists(p))
print("platform env:", os.environ.get("QT_QPA_PLATFORM"))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
fams = QFontDatabase.families() if hasattr(QFontDatabase, "families") else QFontDatabase().families()
print("families:", len(fams), fams[:5])
img = QImage(200, 60, QImage.Format.Format_ARGB32_Premultiplied)
img.fill(Qt.GlobalColor.black)
p = QPainter(img); p.setPen(QColor("#FFFFFF")); p.setFont(QFont("Arial", 30))
p.drawText(10, 40, "ABC"); p.end()
bits = img.convertToFormat(QImage.Format.Format_RGBA8888).constBits()
raw = bits.tobytes() if hasattr(bits, "tobytes") else bytes(bits)
import numpy as np
a = np.frombuffer(raw, np.uint8).reshape(60, 200, 4)
print("lit pixels:", int((a[:, :, 0].astype(int) > 40).sum()))
img.save(os.path.join("scratch", "font_probe.png"))
