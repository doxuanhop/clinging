"""Codec-tolerant frame extraction shared by Player and cover UI."""

from __future__ import annotations

import os
import subprocess

from core import external_tools

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap


def frame_index_at(seconds: float, fps: float) -> int:
    """Quy tac chon frame nguon DUY NHAT cho ca toan app.

    Preview va Export phai quy doi giay -> chi so frame giong het nhau. Truoc
    day export seek theo mili giay (POS_MSEC) con preview seek theo chi so
    (POS_FRAMES), nen cung mot moc thoi gian hai ben co the lay hai frame ke
    nhau. Do lech <= 1 frame nguon (khong nhin thay), nhung no la lech he
    thong va khong duoc ton tai o hai noi khac nhau nua.
    """
    if fps <= 0:
        return 0
    return max(0, int(round(float(seconds) * float(fps))))


def qimage_from_bgr(frame) -> QImage:
    """ndarray BGR cua OpenCV -> QImage RGB da copy (buffer tam thoi chet ngay)."""
    import cv2
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    return QImage(rgb.data, width, height, channels * width,
                  QImage.Format_RGB888).copy()


class SequentialVideoReader:
    """Doc video THUAN TIEP: chi seek khi khong con cach khac.

    Do tren may cau hinh thap (i7-2720QM 2011, nguon nam tren HDD 5400 rpm,
    xem scratch/perf_baseline.json): mo container + seek + doc + dong moi frame
    = 492 ms, seek tren capture da mo = 422 ms, nhung doc tiep = 28 ms. Seek
    dat den the la vi moi lan phai quay ve keyframe gan nhat roi giai ma den
    moc yeu cau; video 60fps keyframe thua thi cang tai. Xuat 1 clip 4 giay truoc
    day mat ~59 giay, gan nhu toan bo la seek lap lai.

    self._pos = chi so frame ma lan read() tiep theo tra ve; None = khong ro,
    bat buoc seek.
    """

    # grab() van phai giai ma frame, nen nhay voi = 1 frame (~2-4 ms 720p).
    # Seek dat ~400 ms, vi vay nhay toi 40 frame van re hon seek; vuot qua
    # moi seek. Clip toc do 2x o 24fps chi cach nhau ~5 frame.
    MAX_GRAB_SKIP = 40

    def __init__(self, file_path: str):
        self._path = file_path
        self._cap = None
        self._fps = 0.0
        self._pos = 0
        self._dead = False
        # Frame tra ra lan guoi nhat: clip chay cham hon 1x (0.5x) yeu cau cung
        # mot chi so frame o hai buoc xuat lien tiep. Neu khong nho thi lan thu
        # hai se thay target < self._pos va seek NGUOC — tuc là chậm hơn cả bản
        # cu. Nho mot frame là du cho moi ty le < 1x.
        self._last_index = None
        self._last_frame = None

    @property
    def dead(self) -> bool:
        """True khi OpenCV khong mo duoc file nay — goi y cho duong ffmpeg."""
        return self._dead

    @property
    def fps(self) -> float:
        """FPS ma OpenCV nhin thay trong container (0 khi chua mo)."""
        return self._fps

    @property
    def last_index(self):
        """Chi so frame cua lan doc thanh cong gan nhat, hoac None.

        Frame phai ty ke duoc ve so thu cua no: ten file anh va contact sheet
        do nguoi dung dua vao moc thoi gian de tim lai mot khung hinh, nen
        "thuc te la frame so may" khong duoc suy ra bang mat canh tranh.
        """
        return self._last_index

    def _ensure(self) -> bool:
        if self._dead:
            return False
        if self._cap is not None and self._cap.isOpened():
            return True
        import cv2
        cap = cv2.VideoCapture(self._path)
        if not cap.isOpened():
            cap.release()
            self._dead = True
            return False
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        self._cap, self._fps = cap, float(fps)
        self._pos = 0
        self._last_index = self._last_frame = None
        if self._fps <= 0:
            self._dead = True
            self.close()
            return False
        return True

    def read_bgr(self, seconds: float):
        """Frame theo frame_index_at(), hoac None (EOF/loi) de caller roi xuong
        duong cham hon. Tra ve ndarray BGR nguyen ban cua OpenCV."""
        import cv2
        if not self._ensure():
            return None
        target = frame_index_at(seconds, self._fps)
        if target == self._last_index and self._last_frame is not None:
            return self._last_frame
        if (self._pos is None or target < self._pos
                or target - self._pos > self.MAX_GRAB_SKIP):
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            self._pos = target
        while self._pos < target:
            if not self._cap.grab():
                self._pos = None
                return None
            self._pos += 1
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self._pos = None
            return None
        self._pos = target + 1
        self._last_index, self._last_frame = target, frame
        return frame

    def close(self):
        cap, self._cap = self._cap, None
        self._pos = None
        self._last_index = self._last_frame = None
        if cap is not None:
            cap.release()


def extract_frame(file_path: str, seconds: float = 0.0,
                  target_size: QSize | None = None) -> QPixmap:
    """Return a frame, using OpenCV first and FFmpeg as fallback."""
    image = extract_frame_image(file_path, seconds, target_size)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def extract_frame_image(file_path: str, seconds: float = 0.0,
                        target_size: QSize | None = None) -> QImage:
    """Thread-safe frame extraction; QPixmap conversion stays on UI thread."""
    if not file_path or not os.path.exists(file_path):
        return QImage()
    seconds = max(0.0, float(seconds))
    image = _extract_image_with_opencv(file_path, seconds)
    if image.isNull():
        image = _extract_image_with_ffmpeg(file_path, seconds)
    if not image.isNull() and target_size and target_size.isValid():
        image = image.scaled(
            target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    return image


def _extract_with_opencv(file_path: str, seconds: float) -> QPixmap:
    image = _extract_image_with_opencv(file_path, seconds)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def _extract_image_with_opencv(file_path: str, seconds: float) -> QImage:
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            cap.release()
            return QImage()
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return QImage()
        return qimage_from_bgr(frame)
    except Exception:
        return QImage()


def _extract_with_ffmpeg(file_path: str, seconds: float) -> QPixmap:
    image = _extract_image_with_ffmpeg(file_path, seconds)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def _extract_image_with_ffmpeg(file_path: str, seconds: float) -> QImage:
    ffmpeg = external_tools.find("ffmpeg")
    if not ffmpeg:
        return QImage()
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-ss", f"{seconds:.3f}",
             "-i", file_path, "-frames:v", "1", "-f", "image2pipe",
             "-vcodec", "png", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=12, check=False, startupinfo=startupinfo,
            creationflags=creationflags,
        )
        image = QImage()
        if result.returncode == 0:
            image.loadFromData(result.stdout, "PNG")
        return image
    except (OSError, subprocess.SubprocessError):
        return QImage()
