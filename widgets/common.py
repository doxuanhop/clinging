"""
widgets/common.py
Các widget dùng chung: nút icon (Font Awesome), hiệu ứng đổ bóng, thanh tab có gạch chân
trượt mượt (animated underline), separator...
"""

from PySide6.QtCore import (Qt, QEvent, QPropertyAnimation, QEasingCurve, QRect,
                            QSize, QTimer, Signal)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QPushButton, QToolButton, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QButtonGroup,
    QSizePolicy, QLabel, QFrame
)
import os


def _qta():
    """Lazy import qtawesome - chỉ import khi QApplication đã tồn tại."""
    import qtawesome
    return qtawesome


def add_shadow(widget, blur=24, color=QColor(0, 0, 0, 160), offset=(0, 6)):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(color)
    effect.setOffset(*offset)
    widget.setGraphicsEffect(effect)
    return effect


def icon_pixmap(icon_name, size=24, color=None):
    """Pixmap Font Awesome.

    qtawesome voi mau mac dinh (khong truyen `color`) tra ve pixmap khong co
    pixel khong trong nao - tuc la in ra o trong. Vi the mau phai duoc nuong
    trong code, du khi khong goi ra mau cu the.
    """
    return _qta().icon(icon_name, color=color or icon_color()).pixmap(size, size)


def font_icon(icon_name, color=None):
    """QIcon Font Awesome cho QPushButton/QAction.

    Mọi biểu tượng công cụ và menu phải đi qua đây. Emoji trong chuỗi văn bản
    phụ thuộc font hệ thống, nên cùng một bản dựng hiện ra khác nhau trên mỗi
    máy và không đổi màu theo chủ đề tối được.
    """
    return _qta().icon(icon_name, color=color or icon_color())


def set_label_icon(label, icon_name, size=24, color=None):
    label.setPixmap(icon_pixmap(icon_name, size, color))
    label.setAlignment(Qt.AlignCenter)


def icon_color():
    """Trả về màu icon phù hợp với theme hiện tại."""
    from theme import theme_manager
    return "#FFFFFF" if theme_manager.mode == "dark" else "#4A4D5A"


def app_icon_path():
    """Single source for window, taskbar and in-app branding."""
    import sys
    from pathlib import Path
    # Bản dựng PyInstaller (onefile) giải nén tài nguyên vào _MEIPASS, còn
    # widgets/common.py thì không nằm trên đĩa.
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / "app-icon" / "icon.png"


def app_icon():
    return QIcon(str(app_icon_path()))


class IconButton(QToolButton):
    """Nút icon dùng Font Awesome - dùng cho toolbar, timeline, playback..."""

    @staticmethod
    def _qta_icon(icon_name, color=None):
        return font_icon(icon_name, color)

    def __init__(self, glyph, tooltip="", object_name="IconGhostBtn",
                 size=34, font_size=14, icon_name=None, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size, size)

        if icon_name:
            self.setIcon(self._qta_icon(icon_name, icon_color()))
            # Preserve the click target while keeping toolbar glyphs light.
            glyph_size = max(10, size - 14)
            self.setIconSize(QSize(glyph_size, glyph_size))
        else:
            self.setText(glyph)
            f = self.font()
            f.setPointSize(font_size)
            self.setFont(f)


class LogoBadge(QWidget):
    """Huy hiệu logo Clinqing: hình vuông bo góc, nền gradient tím,
    bên trong là biểu tượng monogram vẽ tay bằng QPainter (không cần ảnh)."""

    def __init__(self, size=38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        from PySide6.QtCore import Qt as _Qt
        pixmap = QPixmap(str(app_icon_path()))
        if not pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled = pixmap.scaled(
                self.size(), _Qt.KeepAspectRatio, _Qt.SmoothTransformation
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
            painter.end()
            return
        from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPainterPath
        from PySide6.QtCore import QRectF, Qt as _Qt

        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor("#40E0D0"))
        grad.setColorAt(1.0, QColor("#2C6E64"))
        p.setPen(_Qt.NoPen)
        p.setBrush(grad)
        radius = w * 0.28
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        pen = QColor("#FFFFFF")
        p.setPen(pen)
        p.setBrush(_Qt.NoBrush)
        from PySide6.QtGui import QPen
        stroke = QPen(pen)
        stroke.setWidthF(w * 0.13)
        stroke.setCapStyle(_Qt.RoundCap)
        p.setPen(stroke)
        margin = w * 0.24
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        p.drawArc(rect, 20 * 16, 300 * 16)

        p.setPen(_Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        dot_r = w * 0.09
        p.drawEllipse(QRectF(w * 0.52, h * 0.42, dot_r * 2, dot_r * 2))
        p.end()


class VSeparator(QFrame):
    """Đường kẻ dọc phân cách nhẹ giữa các cụm nút trên toolbar."""

    def __init__(self, height=22, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFixedHeight(height)
        self.setStyleSheet("background-color: #262835; max-width:1px; border:none;")


class AnimatedTabBar(QWidget):
    """
    Thanh tab dạng chữ với gạch chân trượt mượt khi đổi tab.
    """

    currentChanged = Signal(int)

    def __init__(self, labels, object_name="LibTab", underline_h=3,
                 spacing=22, parent=None):
        super().__init__(parent)
        self._buttons = []
        self.underline_h = underline_h

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        for i, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setObjectName(object_name)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            self.group.addButton(btn, i)
            row.addWidget(btn)
            self._buttons.append(btn)
        row.addStretch(1)
        outer.addLayout(row)

        self.track = QFrame(self)
        self.track.setObjectName("TabTrack")
        self.track.setFixedHeight(1)
        self.underline = QFrame(self)
        self.underline.setObjectName("TabUnderline")
        self.underline.setFixedHeight(underline_h)

        outer.addSpacing(1)
        outer.addWidget(self.track)

        self._anim = QPropertyAnimation(self.underline, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.group.idClicked.connect(self._on_clicked)
        if self._buttons:
            self._buttons[0].setChecked(True)

    def _on_clicked(self, idx):
        self.currentChanged.emit(idx)
        self._slide_to(idx)

    def showEvent(self, event):
        super().showEvent(event)
        checked_id = self.group.checkedId()
        if checked_id >= 0:
            self._slide_to(checked_id, animate=False)

    def _slide_to(self, idx, animate=True):
        if idx < 0 or idx >= len(self._buttons):
            return
        btn = self._buttons[idx]
        target = QRect(btn.x(), self.track.y() - 1, btn.width(), self.underline_h)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self.underline.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.underline.setGeometry(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.track.setGeometry(0, self.track.y(), self.width(), 2)
        checked_id = self.group.checkedId()
        if checked_id >= 0:
            self._slide_to(checked_id, animate=False)

    def setCurrentIndex(self, idx):
        if 0 <= idx < len(self._buttons):
            self._buttons[idx].setChecked(True)
            self._slide_to(idx)


class FadeStack(QWidget):
    """Bọc quanh QStackedWidget để tạo hiệu ứng fade-in mượt khi đổi trang."""

    def __init__(self, stacked_widget, parent=None):
        super().__init__(parent)
        self.stacked = stacked_widget
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._effect = QGraphicsOpacityEffect(self.stacked)
        self.stacked.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity")
        self._anim.setDuration(220)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked)

    def set_index(self, index):
        self.stacked.setCurrentIndex(index)
        self._anim.stop()
        self._anim.start()


def open_local_file(path) -> bool:
    """Mở file/thư mục bằng ứng dụng mặc định của hệ điều hành.

    Dùng QDesktopServices chứ không spawn `start`/`explorer`: đường dẫn của
    người dùng chứa dấu cách, nháy kép và ký tự Unicode, và một tiến trình shell
    trung gian sẽ phải tự đoán lại cách ghép những ký tự đó. Trả về False khi
    đường dẫn không còn tồn tại — đúng lúc người dùng vừa xoá file vừa xuất.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if not path or not os.path.exists(path):
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path))))


class Toast(QWidget):
    """Banner nổi ở góc dưới-phải của MỘT cửa sổ, tự tắt sau vài giây.

    Toast là widget CON của host, không phải cửa sổ riêng. Lý do: hộp thoại
    Xuất video là modal và chặn tương tác với cửa sổ chính, nên một toast đặt
    ở cửa sổ chính đúng lúc xuất xong sẽ hiện ra mà không bấm được. Là con thì
    nó theo host khi host đổi kích thước (event filter) và chết cùng host.

    Mỗi host chỉ một toast: toast mới thay toast cũ ngay lập tức, không xếp
    chồng — hai banner "xuất xong" chồng lên nhau chỉ để người dùng bấm nhầm.
    """

    _LIVE = {}          # id(host) -> Toast, key la int vi widget da bi huy
                        # thi hash() khong con an toan
    WIDTH = 430
    MARGIN = 12

    @classmethod
    def popup(cls, host, title, message="", icon_name="fa6s.circle-check",
              action_label="", action=None, ms=6000, dark=None, y_shift=0):
        """Hiện toast trên `host`. `dark=True` ép bảng màu tối cho host luôn
        tối (hộp thoại Xuất video), kể cả khi app đang ở chủ đề sáng.
        `y_shift` âm để nâng thẻ lên khỏi góc dưới-phải — hộp thoại Xuất có
        nút "Xuất lại" đúng chỗ đó và toast không được đè lên nút."""
        previous = cls._LIVE.get(id(host))
        if previous is not None:
            try:
                previous.destroy_now()
            except RuntimeError:
                # Host cũ đã đóng nên toast bị giải phóng cùng: chủ đề con trỏ
                # chết, chỉ cần xoá dấu vết khỏi _LIVE.
                cls._LIVE.pop(id(host), None)
        toast = cls(host, title, message, icon_name, action_label, action,
                    ms, dark, y_shift)
        return toast

    def __init__(self, host, title, message, icon_name, action_label, action,
                 ms, dark, y_shift=0):
        super().__init__(host)
        self._host = host
        self._action = action if action_label else None
        self._leaving = False
        self._y_shift = int(y_shift)
        self.setObjectName("Toast")

        from theme import Palette, theme_manager
        pal = Palette.DARK if dark else theme_manager.colors

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 10, 10)
        card = QFrame(self)
        card.setObjectName("ToastCard")
        self._card = card
        outer.addWidget(card)
        add_shadow(card, blur=26, color=QColor(0, 0, 0, 170), offset=(0, 6))

        row = QHBoxLayout(card)
        row.setContentsMargins(12, 9, 8, 9)
        row.setSpacing(10)

        icon = QLabel(card)
        set_label_icon(icon, icon_name, 18, pal["accent"])
        row.addWidget(icon)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        lbl_title = QLabel(title, card)
        lbl_title.setObjectName("ToastTitle")
        # Tên file dài thì cắt giữa chứ không dồn toast xuống hai dòng: dòng
        # thứ hai rơi ra ngoài mép dưới của host thấp như hộp thoại Xuất.
        room = self.WIDTH - 210
        text = str(message or "")
        fm = QFontMetrics(lbl_title.font())
        lbl_msg = QLabel(fm.elidedText(text, Qt.ElideMiddle, room), card)
        lbl_msg.setObjectName("ToastMsg")
        lbl_msg.setToolTip(text)
        texts.addWidget(lbl_title)
        texts.addWidget(lbl_msg)
        row.addLayout(texts)
        row.addStretch(1)

        if action_label:
            btn = QPushButton(action_label, card)
            btn.setObjectName("ToastAction")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._trigger)
            row.addWidget(btn)

        close = QToolButton(card)
        close.setObjectName("ToastClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setIcon(font_icon("fa6s.xmark", pal["muted"]))
        close.setIconSize(QSize(11, 11))
        close.setFixedSize(20, 20)
        close.clicked.connect(self.fade_out)
        row.addWidget(close)

        self.setStyleSheet("""
            QWidget#Toast { background: transparent; }
            QFrame#ToastCard { background: %s; border: 1px solid %s;
                               border-radius: 10px; }
            QLabel#ToastTitle { color: %s; font-size: 13px; font-weight: 600;
                                background: transparent; border: none; }
            QLabel#ToastMsg { color: %s; font-size: 11px; background: transparent;
                              border: none; }
            QPushButton#ToastAction { color: %s; background: transparent;
                border: 1px solid %s; border-radius: 6px; padding: 4px 10px;
                font-size: 11px; font-weight: 600; }
            QPushButton#ToastAction:hover { background: %s; color: %s; }
            QToolButton#ToastClose { border: none; background: transparent; }
        """ % (pal["panel"], pal["border"], pal["text"], pal["muted"],
               pal["accent"], pal["accent"], pal["accent"], pal["bg"]))

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(170)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)

        card.installEventFilter(self)
        host.installEventFilter(self)
        self._LIVE[id(host)] = self

        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self._anim.start()
        self._timer.start(max(1500, int(ms)))

    # ── hành vi ─────────────────────────────────────────────────

    def place(self):
        host_w = max(0, self._host.width())
        host_h = max(0, self._host.height())
        hint = self.sizeHint()
        w = min(hint.width(), max(220, host_w - 2 * self.MARGIN))
        self.resize(w, hint.height())
        y = host_h - self.height() - self.MARGIN + self._y_shift
        self.move(max(4, host_w - w - self.MARGIN),
                  min(max(4, y), max(4, host_h - self.height() - 4)))
        self.raise_()

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self._host and kind == QEvent.Resize:
            self.place()
        elif obj is self._card and kind == QEvent.MouseButtonPress:
            # Bấm vào thân card = bấm nút hành động: toast "xuất xong" tồn tại
            # chỉ để mở file, bắt người dùng nhắm đúng cái nút nhỏ là thừa.
            if self._action is not None:
                self._trigger()
                return True
        return super().eventFilter(obj, event)

    def _trigger(self):
        action, self._action = self._action, None
        if action is not None:
            action()
        self.fade_out()

    def fade_out(self):
        if self._leaving:
            return
        self._timer.stop()
        self._leaving = True
        self._anim.stop()
        self._anim.setDirection(QPropertyAnimation.Backward)
        self._anim.start()

    def destroy_now(self):
        """Tắt tức thì (không fade) — dùng khi toast mới chiếm chỗ toast cũ."""
        self._timer.stop()
        self._leaving = True
        self._detach()
        self.hide()
        self.deleteLater()

    def _on_anim_done(self):
        if self._leaving:
            self._detach()
            self.hide()
            self.deleteLater()

    def _detach(self):
        key = id(self._host)
        if self._LIVE.get(key) is self:
            self._LIVE.pop(key, None)
        try:
            self._host.removeEventFilter(self)
        except RuntimeError:
            pass
