"""Nối hộp thoại Lớp phủ recap: nút ở TimelineHeader -> tín hiệu -> MainWindow."""
import io

ROOT = r"D:\Programming\clinging"


def patch(rel, pairs):
    path = ROOT + "\\" + rel
    s = io.open(path, "r", encoding="utf-8", newline="").read()
    crlf = "\r\n" in s
    for old, new in pairs:
        if crlf:
            old = old.replace("\n", "\r\n")
            new = new.replace("\n", "\r\n")
        assert s.count(old) == 1, (rel, s.count(old), old[:60])
        s = s.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="").write(s)
    import ast
    ast.parse(s.replace("\r\n", "\n"))
    print("patched", rel, "CRLF" if crlf else "LF")


patch("ui/timeline_panel.py", [
    ("    duplicateRequested = Signal()\n    themeToggleRequested = Signal()\n",
     "    duplicateRequested = Signal()\n    themeToggleRequested = Signal()\n"
     "    recapOverlayRequested = Signal()\n"),
    ("        # ── Theme Toggle Button ──\n        layout.addSpacing(10)\n",
     "        # ── Lớp phủ recap (cấu hình cả dự án, mở hộp thoại riêng) ──\n"
     "        self.btn_recap = IconButton(\"\", \"Lớp phủ recap\",\n"
     "                                    object_name=\"TimelineIconBtn\", size=28,\n"
     "                                    icon_name=\"fa6s.crosshairs\")\n"
     "        self.btn_recap.clicked.connect(self.recapOverlayRequested.emit)\n"
     "        layout.addWidget(self.btn_recap)\n"
     "\n"
     "        # ── Theme Toggle Button ──\n        layout.addSpacing(10)\n"),
    ("    coverRequested = Signal(object)   # Main Storyline video clip\n",
     "    coverRequested = Signal(object)   # Main Storyline video clip\n"
     "    recapOverlayRequested = Signal()\n"),
    ("        self.header.themeToggleRequested.connect(self.themeToggleRequested.emit)\n",
     "        self.header.themeToggleRequested.connect(self.themeToggleRequested.emit)\n"
     "        self.header.recapOverlayRequested.connect(self.recapOverlayRequested.emit)\n"),
])

patch("ui/main_window.py", [
    ("        self.timeline_panel.coverRequested.connect(self._open_cover_dialog)\n",
     "        self.timeline_panel.coverRequested.connect(self._open_cover_dialog)\n"
     "        self.timeline_panel.recapOverlayRequested.connect(self._open_recap_overlay)\n"
     "        # Lớp phủ là cấu hình dự án nên model đổi là canvas phải vẽ lại ngay —\n"
     "        # không có clip nào được chọn ở đây để mà dựa vào clipUpdated.\n"
     "        self.timeline_panel.model.recapOverlayChanged.connect(\n"
     "            self._on_recap_overlay_changed)\n"),
    ("    def _open_keyframe_graph(self, clip_id):",
     "    def _open_recap_overlay(self):\n"
     "        \"\"\"Hộp thoại Lớp phủ recap — một instance, cấu hình sống theo dự án.\"\"\"\n"
     "        from ui.recap_overlay_dialog import RecapOverlayDialog\n"
     "        dialog = getattr(self, \"_recap_dialog\", None)\n"
     "        if dialog is None:\n"
     "            dialog = RecapOverlayDialog(self)\n"
     "            self._recap_dialog = dialog\n"
     "        dialog.show()\n"
     "        dialog.raise_()\n"
     "        dialog.activateWindow()\n"
     "        return dialog\n"
     "\n"
     "    def _on_recap_overlay_changed(self, _settings):\n"
     "        self.preview_panel.canvas.viewport().update()\n"
     "\n"
     "    def _open_keyframe_graph(self, clip_id):"),
])
