"""
ui/custom_dialog.py
Hộp thoại tùy chỉnh với Title Bar tự thiết kế — thay thế QMessageBox mặc định.
Không dùng Native Window Title Bar của Windows.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QWidget, QLineEdit, QScrollArea, QApplication
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPen, QBrush

from widgets.common import font_icon


# ── Styles ─────────────────────────────────────────────────────

_DIALOG_STYLE = """
    QDialog {
        background-color: #1A1C1F;
        border: 1px solid #34383D;
        border-radius: 14px;
        color: #D8DCE0;
    }
"""

_TITLE_BAR_STYLE = """
    QFrame {
        background-color: #1A1C1F;
        border-bottom: 1px solid #2A2E34;
        border-top-left-radius: 14px;
        border-top-right-radius: 14px;
    }
"""

_BODY_STYLE = """
    QFrame {
        background: transparent;
        border: none;
    }
"""

_BTN_PRIMARY = """
    QPushButton {
        background-color: #2C6E64;
        color: #EAFFFB;
        border: 1px solid #40E0D0;
        border-radius: 8px;
        padding: 8px 24px;
        font-weight: bold;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #348175; }
    QPushButton:pressed { background-color: #245A52; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #252729;
        color: #D8DCE0;
        border: 1px solid #3A3A3A;
        border-radius: 8px;
        padding: 8px 24px;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #303234; border-color: #40E0D0; }
"""

_BTN_DANGER = """
    QPushButton {
        background-color: #DC2626;
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        padding: 8px 24px;
        font-weight: bold;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #EF4444; }
"""


# ── Icon Painter ───────────────────────────────────────────────

def _paint_info_icon(painter, size=32):
    """Vẽ icon Info (i trong vòng tròn)."""
    painter.setRenderHint(QPainter.Antialiasing)
    r = size // 2
    cx, cy = r, r
    painter.setPen(QPen(QColor("#40E0D0"), 2))
    painter.setBrush(QBrush(QColor("#2C6E64")))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", max(10, r - 4), QFont.Bold)
    painter.setFont(font)
    painter.drawText(0, 0, size, size, Qt.AlignCenter, "i")


def _paint_warning_icon(painter, size=32):
    """Vẽ icon Warning (tam giác cảnh báo)."""
    painter.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QPolygonF
    from PySide6.QtCore import QPointF
    tri = QPolygonF([
        QPointF(size / 2, 2),
        QPointF(size - 4, size - 4),
        QPointF(4, size - 4),
    ])
    painter.setPen(QPen(QColor("#F59E0B"), 2))
    painter.setBrush(QBrush(QColor("#F59E0B")))
    painter.drawPolygon(tri)
    painter.setPen(QColor("#000000"))
    font = QFont("Segoe UI", max(10, size // 3), QFont.Bold)
    painter.setFont(font)
    painter.drawText(0, 4, size, size - 6, Qt.AlignCenter, "!")


def _paint_error_icon(painter, size=32):
    """Vẽ icon Error (X trong vòng tròn đỏ)."""
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#DC2626"), 2))
    painter.setBrush(QBrush(QColor("#DC2626")))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QPen(QColor("#FFFFFF"), 2))
    m = size // 3
    painter.drawLine(m, m, size - m, size - m)
    painter.drawLine(size - m, m, m, size - m)


def _paint_question_icon(painter, size=32):
    """Vẽ icon Question (? trong vòng tròn)."""
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#40E0D0"), 2))
    painter.setBrush(QBrush(QColor("#2C6E64")))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", max(10, size // 3), QFont.Bold)
    painter.setFont(font)
    painter.drawText(0, 0, size, size, Qt.AlignCenter, "?")


def _paint_success_icon(painter, size=32):
    """Vẽ icon Success (dấu check trong vòng tròn xanh)."""
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#16A34A"), 2))
    painter.setBrush(QBrush(QColor("#16A34A")))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QPen(QColor("#FFFFFF"), 3))
    m = size // 3
    painter.drawLine(m + 2, size // 2, size // 2 - 1, size - m)
    painter.drawLine(size // 2 - 1, size - m, size - m - 2, m + 4)


# ── Custom Dialog ──────────────────────────────────────────────

class CustomDialog(QDialog):
    """
    Hộp thoại tùy chỉnh với Title Bar tự thiết kế.
    Thay thế QMessageBox với giao diện dark theme thống nhất.
    """

    def __init__(self, title, message, parent=None, icon_type="info",
                 buttons=None, default_button=None):
        """
        icon_type: "info", "warning", "error", "question", "success"
        buttons: list of (text, role) — role: "accept", "reject", "danger"
        default_button: index của button mặc định
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setStyleSheet(_DIALOG_STYLE)

        self._result = None
        self._buttons = buttons or [("OK", "accept")]
        self._icon_type = icon_type
        self._default_button = default_button

        self._build_ui(title, message)
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.82))
        self._center_on_parent()

    def _build_ui(self, title, message):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title Bar ──
        title_frame = QFrame()
        title_frame.setStyleSheet(_TITLE_BAR_STYLE)
        title_frame.setFixedHeight(46)
        tb_layout = QHBoxLayout(title_frame)
        tb_layout.setContentsMargins(18, 0, 12, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #FFFFFF; "
            "background: transparent; border: none;"
        )
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()

        btn_close = QPushButton()
        btn_close.setFixedSize(28, 28)
        btn_close.setIcon(font_icon("fa6s.xmark", "#C8CBD4"))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #E81123; }
        """)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        root.addWidget(title_frame)

        # ── Body ──
        body = QFrame()
        body.setStyleSheet(_BODY_STYLE)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 16)
        body_layout.setSpacing(16)

        # Icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_lbl.paintEvent = lambda e: self._paint_icon(icon_lbl)
        body_layout.addWidget(icon_lbl, 0, Qt.AlignTop)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "font-size: 13px; color: #D0D0D0; line-height: 1.5; "
            "background: transparent; border: none;"
        )
        body_layout.addWidget(msg_lbl, 1)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setWidget(body)
        root.addWidget(body_scroll, 1)

        # ── Button Row ──
        btn_frame = QFrame()
        btn_frame.setStyleSheet(_BODY_STYLE)
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(24, 8, 24, 18)
        btn_layout.addStretch()

        self._btn_widgets = []
        for i, (text, role) in enumerate(self._buttons):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumWidth(90)

            if role == "danger":
                btn.setStyleSheet(_BTN_DANGER)
            elif role == "reject":
                btn.setStyleSheet(_BTN_SECONDARY)
            else:
                btn.setStyleSheet(_BTN_PRIMARY)

            btn.clicked.connect(lambda checked, idx=i: self._on_button(idx))
            btn_layout.addWidget(btn)
            self._btn_widgets.append(btn)

            if i < len(self._buttons) - 1:
                btn_layout.addSpacing(8)

        root.addWidget(btn_frame)

        # Set default button
        if self._default_button is not None and 0 <= self._default_button < len(self._btn_widgets):
            self._btn_widgets[self._default_button].setDefault(True)
            self._btn_widgets[self._default_button].setFocus()
        elif self._btn_widgets:
            self._btn_widgets[-1].setDefault(True)
            self._btn_widgets[-1].setFocus()

    def _paint_icon(self, label):
        painter = QPainter(label)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._icon_type == "warning":
            _paint_warning_icon(painter, 36)
        elif self._icon_type == "error":
            _paint_error_icon(painter, 36)
        elif self._icon_type == "question":
            _paint_question_icon(painter, 36)
        elif self._icon_type == "success":
            _paint_success_icon(painter, 36)
        else:
            _paint_info_icon(painter, 36)
        painter.end()

    def _on_button(self, index):
        self._result = index
        text, role = self._buttons[index]
        if role == "accept":
            self.accept()
        elif role == "reject" or role == "danger":
            self.reject()

    def _center_on_parent(self):
        self.adjustSize()
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)
        elif self.parent():
            parent_geo = self.parent().geometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
            self.move(x, y)

    def result(self):
        return self._result

    def result_text(self):
        if self._result is not None:
            return self._buttons[self._result][0]
        return ""

    # ── Static convenience methods (drop-in QMessageBox replacements) ──

    @staticmethod
    def information(parent, title, message):
        dlg = CustomDialog(title, message, parent, icon_type="info",
                          buttons=[("OK", "accept")], default_button=0)
        dlg.exec()
        return dlg.result()

    @staticmethod
    def warning(parent, title, message):
        dlg = CustomDialog(title, message, parent, icon_type="warning",
                          buttons=[("OK", "accept")], default_button=0)
        dlg.exec()
        return dlg.result()

    @staticmethod
    def critical(parent, title, message):
        dlg = CustomDialog(title, message, parent, icon_type="error",
                          buttons=[("OK", "accept")], default_button=0)
        dlg.exec()
        return dlg.result()

    @staticmethod
    def question(parent, title, message, buttons=None):
        if buttons is None:
            buttons = [("Có", "accept"), ("Không", "reject")]
        dlg = CustomDialog(title, message, parent, icon_type="question",
                          buttons=buttons, default_button=1)
        dlg.exec()
        if dlg.result() == 0:
            return True
        return False

    @staticmethod
    def success(parent, title, message):
        dlg = CustomDialog(title, message, parent, icon_type="success",
                          buttons=[("OK", "accept")], default_button=0)
        dlg.exec()
        return dlg.result()


# ── Custom Input Dialog ───────────────────────────────────────

_INPUT_STYLE = """
    QLineEdit {
        background-color: #1A1B22;
        border: 1px solid #2A2C38;
        border-radius: 6px;
        padding: 8px 12px;
        color: #E0E0E0;
        font-size: 13px;
        selection-background-color: #2C6E64;
    }
    QLineEdit:focus {
        border-color: #40E0D0;
    }
"""


class CustomInputDialog(QDialog):
    """
    Hộp thoại nhập liệu tùy chỉnh — thay thế QInputDialog.
    Trả về (text, ok) giống QInputDialog.getText().
    """

    def __init__(self, title, label, text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setStyleSheet(_DIALOG_STYLE)
        screen = QApplication.primaryScreen()
        if screen:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.82))
        self._result_text = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title Bar ──
        title_frame = QFrame()
        title_frame.setStyleSheet(_TITLE_BAR_STYLE)
        title_frame.setFixedHeight(46)
        tb_layout = QHBoxLayout(title_frame)
        tb_layout.setContentsMargins(18, 0, 12, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #FFFFFF; "
            "background: transparent; border: none;"
        )
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()

        btn_close = QPushButton()
        btn_close.setFixedSize(28, 28)
        btn_close.setIcon(font_icon("fa6s.xmark", "#C8CBD4"))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #E81123; }
        """)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)
        root.addWidget(title_frame)

        # ── Body ──
        body = QFrame()
        body.setStyleSheet(_BODY_STYLE)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 16)
        body_layout.setSpacing(8)

        # Icon + Label row
        icon_row = QHBoxLayout()
        icon_row.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_lbl.paintEvent = lambda e: _paint_info_icon(QPainter(icon_lbl), 36)
        icon_row.addWidget(icon_lbl, 0, Qt.AlignTop)

        label_lbl = QLabel(label)
        label_lbl.setWordWrap(True)
        label_lbl.setStyleSheet(
            "font-size: 13px; color: #D0D0D0; line-height: 1.5; "
            "background: transparent; border: none;"
        )
        icon_row.addWidget(label_lbl, 1)
        body_layout.addLayout(icon_row)

        # Input field
        self.input = QLineEdit(text)
        self.input.setStyleSheet(_INPUT_STYLE)
        self.input.setFixedHeight(36)
        self.input.returnPressed.connect(self._on_accept)
        body_layout.addWidget(self.input)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setWidget(body)
        root.addWidget(body_scroll, 1)

        # ── Button Row ──
        btn_frame = QFrame()
        btn_frame.setStyleSheet(_BODY_STYLE)
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(24, 8, 24, 18)
        btn_layout.addStretch()

        cancel_btn = QPushButton("Hủy")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumWidth(90)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addSpacing(8)

        ok_btn = QPushButton("Đồng ý")
        ok_btn.setStyleSheet(_BTN_PRIMARY)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setMinimumWidth(90)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        root.addWidget(btn_frame)

        # Center
        self.adjustSize()
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)
        elif parent:
            pg = parent.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 2
            self.move(x, y)

    def _on_accept(self):
        self._result_text = self.input.text().strip()
        self.accept()

    def get_text(self):
        return self._result_text

    @staticmethod
    def getText(parent, title, label, text=""):
        """Drop-in replacement for QInputDialog.getText(). Returns (text, ok)."""
        dlg = CustomInputDialog(title, label, text, parent)
        result = dlg.exec()
        return (dlg.get_text(), result == QDialog.Accepted)
