"""
ui/keyframe_graph_dialog.py
Đồ thị đường cong keyframe: xem và sửa chuyển động theo thời gian.

Mỗi property có keyframe được MỘT DẢI RIÊNG, tự co theo khoảng giá trị của
chính nó — vị trí (px), co giãn (×), góc xoay (°) và độ mờ (%) không chung
được một trục tung. Đường cong vẽ bằng ``core.keyframe_graph.sample_curve``,
tức đúng ``interpolate_keyframes`` mà preview và export đang dùng: thứ người
ta nhìn trên đồ thị là thứ sẽ render ra file.

Sửa gì cũng đi qua undo stack của timeline (Add/Edit/Remove/SetEase), nên một
cú kéo trên đồ thị hoàn tác được y như bấm nút kim cương.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QActionGroup, QBrush, QColor, QFont, QFontMetrics,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core import keyframe_graph as graph
from core.commands import (AddKeyframeCommand, EditKeyframeCommand,
                           RemoveKeyframeCommand, SetKeyframeEaseCommand)
from core.keyframe_manager import (EASE_LABELS, EASINGS, apply_ease, frame_ease,
                                   frame_time, frame_value)
from widgets.common import font_icon

GUTTER_LEFT = 128
GUTTER_RIGHT = 18
AXIS_HEIGHT = 22
TOP_PAD = 12
# Nhan gia tri nam BAT KE o vach tren/duoi cua lane, nen hai lane phai cach
# nhau du cho hai dong chu khong de len nhau.
LANE_GAP = 18
LANE_MIN_HEIGHT = 44.0
# Luoi cua moi lane luon chia 4 o; day la so khoang LON NHAT nhan truc tung
# duoc in ra. Nhan deu nhau nen so nhan in ra = divisions + 1.
GRID_DIVISIONS = 4
# Khoang cach toi thieu giua hai dong nhan ke nhau, tinh theo chieu cao chu.
LABEL_CLEARANCE = 4.0
NODE_RADIUS = 7.0
HIT_RADIUS = 10.0
HANDLE_LENGTH = 6.0

BACKGROUND = QColor("#14151A")
LANE_FILL = QColor("#171922")
LANE_EDGE = QColor("#22242C")
GRID_LINE = QColor("#1E2028")
AXIS_TEXT = QColor("#6E7482")
NODE_FILL = QColor("#F2F3F7")
PLAYHEAD = QColor("#40E0D0")

PROPERTY_COLORS = {
    "x": QColor("#40E0D0"),
    "y": QColor("#7C9CFF"),
    "scale_x": QColor("#F5A524"),
    "scale_y": QColor("#E85D9A"),
    "rotation": QColor("#56C596"),
    "opacity": QColor("#B9A0FF"),
}
FALLBACK_COLOR = QColor("#40E0D0")

TIME_STEPS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0)

# Le phai cua vung ve = ben phai nhat cua cot so trong le trai.
VALUE_LABEL_RIGHT = GUTTER_LEFT - 18

# Duong vong duoc chon qua menu, nen menu phai co mot token "xoa" khong trung
# ten nao trong EASINGS.
REMOVE_TOKEN = "__remove__"


def color_of(prop):
    return PROPERTY_COLORS.get(prop, FALLBACK_COLOR)


def time_step(duration: float) -> float:
    """Buoc thoi gian de lai duoi truc: du cho co duoi ~8 vach ke."""
    span = max(0.001, float(duration))
    for step in TIME_STEPS:
        if span / step <= 8:
            return step
    return TIME_STEPS[-1]


def tick_times(t1: float) -> list:
    """Das cac vach thoi gian tu 0 den het do dai clip."""
    step = time_step(t1)
    ticks = []
    tick = 0.0
    while tick <= t1 + 1e-9:
        ticks.append(tick)
        tick += step
    return ticks


def lane_label(prop) -> str:
    return graph.PROPERTY_LABELS.get(prop, prop)


def label_divisions(height: float, label_h: float) -> int:
    """Số khoảng nhãn trục tung in ra trong một lane cao ``height`` px.

    Hai điều phải tránh cùng lúc:
      * Một lane 48 px (chiều cao thật khi mở đủ 6 property) không chứa nổi năm
        dòng chữ 16 px — chúng đè lên nhau thành một bó số không đọc được.
      * Nhãn nằm BÊN TRONG lane, không vượt qua lề, nên khoảng dùng được là
        ``height - label_h``, không phải ``height``.

    Lưới vẫn giữ bốn ô để còn đo được; nhãn phải đều nhau nên số khoảng chỉ có
    thể 4 → 2 → 1.
    """
    usable = float(height) - float(label_h)
    divisions = GRID_DIVISIONS
    while divisions > 1 and usable / divisions < label_h + LABEL_CLEARANCE:
        divisions //= 2
    return divisions


def curve_at(clip, lane, time):
    """Gia tri duong cong THAT tai thoi diem do — do thi khong co loi noi suy
    rieng, nen moc them o day trung voi diem preview/export se render."""
    return graph.interpolate_at(lane.frames, lane.prop,
                                graph.default_value(clip, lane.prop), time)


def handle_slope(ease) -> float:
    """Do doc tai dau doan, lay tu dao ham that cua bang EASINGS."""
    step = 0.05
    slope = (apply_ease(ease, step) - apply_ease(ease, 0.0)) / step
    return max(-1.5, min(1.5, slope))


def ease_before(clip, prop, time):
    """Duong cong cua moc gan nhat phia truoc — moc moi tiep noi khop voi
    doan dang chay, khong bat ngo doi tam nhin."""
    frames = graph.frames_of(clip, prop)
    earlier = [f for f in frames if frame_time(f) <= time + 1e-6]
    return frame_ease(earlier[-1]) if earlier else None


class _Lane:
    """Một hàng của một property: dữ liệu + hình chữ nhật vẽ đã chiếu xong."""

    __slots__ = ("prop", "frames", "t1", "lo", "hi", "rect")

    def __init__(self, prop, frames, t1, lo, hi, rect):
        self.prop = prop
        self.frames = frames
        self.t1 = t1
        self.lo = lo
        self.hi = hi
        self.rect = rect

    def x_of(self, time):
        return graph.time_to_x(time, 0.0, self.t1, self.rect.left(),
                               self.rect.right())

    def y_of(self, raw):
        return graph.value_to_y(graph.display_value(self.prop, raw), self.lo,
                                self.hi, self.rect.top(), self.rect.bottom())

    def time_at(self, x):
        return graph.clamp(graph.x_to_time(x, 0.0, self.t1, self.rect.left(),
                                           self.rect.right()), 0.0, self.t1)

    def value_at(self, y):
        """Nguoc cua y_of, co vao trong dai dang hien.

        Khi keo, duong phai co dinh (tinh theo moc cu, khong theo moc dang
        di), neu khong thi moi lan keo lam hi sinh mot gia tri ngoai lai va
        duoi thang do da chenh duoi con tro.
        """
        shown = graph.clamp(
            graph.y_to_value(y, self.lo, self.hi, self.rect.top(),
                             self.rect.bottom()), self.lo, self.hi)
        return graph.raw_value(self.prop, shown)


class KeyframeGraphView(QWidget):
    """Vùng vẽ đồ thị. Chỉ nhìn model, không tự giữ bản sao keyframe nào."""

    edited = Signal(str)          # property vừa sửa — để hộp thoại đồng bộ timeline

    def __init__(self, model, clip_id: str, undo_stack, parent=None):
        super().__init__(parent)
        self._model = model
        self._clip_id = clip_id
        self._undo = undo_stack
        self._drag = None          # (prop, index, frame_goc, time, value)
        self._selected = None      # (prop, time)
        self._hover_node = False
        self.setMinimumSize(420, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        # Phai co focus thi phim Delete moi den duoc day.
        self.setFocusPolicy(Qt.StrongFocus)

        model.playheadChanged.connect(self._on_playhead)
        for signal in (model.clipResized, model.clipUpdated, model.clipMoved):
            signal.connect(self._on_model_changed)

    # ── Dữ liệu ────────────────────────────────────────────────

    def _on_playhead(self, _time):
        self.update()

    def _on_model_changed(self, *_args):
        self.update()

    def clip(self):
        return self._model.get_clip(self._clip_id)

    @property
    def clip_id(self):
        return self._clip_id

    def set_clip(self, clip_id: str):
        """Doi clip cua mot view dang mo — hop thoai chi co MỘT instance."""
        self._clip_id = clip_id
        self._drag = None
        self._selected = None
        self.update()

    def _draw_frames(self, prop, clip):
        """Keyframe cua property, co thay bang tam moc dang bi keo.

        Luc keo thi duong cong phai uot theo tay nguoi dung ngay truong mat,
        nen ban ve dung frame tam; model chi nhan khi tha chuot.
        """
        frames = graph.frames_of(clip, prop)
        if not self._drag or self._drag[0] != prop:
            return frames
        _prop, index, old_frame, time, value = self._drag
        preview = list(frames)
        if index < len(preview):
            preview[index] = (time, value, frame_ease(old_frame))
        return preview

    def _lanes(self, clip):
        lanes = []
        props = graph.animated_properties(clip)
        if not props:
            return lanes
        area = self.rect().adjusted(GUTTER_LEFT, TOP_PAD, -GUTTER_RIGHT,
                                    -(AXIS_HEIGHT + 8))
        gap = LANE_GAP * (len(props) - 1)
        height = max(LANE_MIN_HEIGHT, (area.height() - gap) / len(props))
        top = area.top()
        duration = max(0.001, float(clip.duration))
        for prop in props:
            base = graph.frames_of(clip, prop)
            lo, hi = graph.value_domain(base, prop,
                                        graph.default_value(clip, prop))
            rect = QRectF(area.left(), top, area.width(), height)
            lanes.append(_Lane(prop, self._draw_frames(prop, clip), duration,
                                lo, hi, rect))
            top += height + LANE_GAP
        return lanes

    # ── Vẽ ─────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), BACKGROUND)
        clip = self.clip()
        if clip is None:
            self._paint_message(painter, "Clip này không còn trong dự án.")
            return
        lanes = self._lanes(clip)
        if not lanes:
            self._paint_message(
                painter, "Chưa có keyframe.\nBấm nút kim cương cạnh một thông"
                         " số trên bảng thuộc tính,\nhoặc nhấn Thêm mốc tại"
                         " playhead.")
            return
        for lane in lanes:
            self._paint_lane(painter, lane, clip)
        self._paint_axis(painter, lanes[-1])
        self._paint_playhead(painter, lanes, clip)

    def _paint_message(self, painter, text):
        painter.setPen(QPen(AXIS_TEXT))
        painter.drawText(self.rect().adjusted(20, 20, -20, -20),
                         Qt.AlignCenter | Qt.TextWordWrap, text)

    def _paint_lane(self, painter, lane, clip):
        rect = lane.rect
        accent = color_of(lane.prop)
        font = QFont(self.font())
        font.setPointSizeF(8.4)
        painter.setFont(font)

        painter.setPen(QPen(LANE_EDGE))
        painter.setBrush(QBrush(LANE_FILL))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 4, 4)
        painter.setBrush(Qt.NoBrush)

        # Luoi + nhan truc tung. Luoi LUON chia 4 o; con nhan thi gian cach
        # theo chieu cao lane va nam BEN TRONG lane — ke o dinh/day lane ma
        # bat qua le thi no de len nhan cua lane lang gieng.
        label_h = QFontMetrics(font).height()
        divisions = label_divisions(rect.height(), label_h)
        step = GRID_DIVISIONS // divisions
        half = label_h / 2.0
        for division in range(GRID_DIVISIONS + 1):
            ratio = division / float(GRID_DIVISIONS)
            y = rect.bottom() - ratio * rect.height()
            painter.setPen(QPen(GRID_LINE))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            if division % step:
                continue
            centre = min(max(y, rect.top() + half), rect.bottom() - half)
            painter.setPen(QPen(AXIS_TEXT))
            painter.drawText(QRectF(0, centre - half, VALUE_LABEL_RIGHT,
                                    label_h),
                             Qt.AlignRight | Qt.AlignVCenter,
                             graph.format_value(lane.prop,
                                                graph.raw_value(lane.prop,
                                                                lane.lo + ratio
                                                                * (lane.hi
                                                                   - lane.lo))))

        # Duong cong noi suy THAT cua model.
        default = graph.default_value(clip, lane.prop)
        samples = graph.sample_curve(lane.frames, lane.prop, default, 0.0,
                                     lane.t1,
                                     samples=max(24, int(rect.width())))
        path = QPainterPath()
        for index, (time, value) in enumerate(samples):
            point = QPointF(lane.x_of(time), lane.y_of(value))
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QPen(accent, 1.8))
        painter.drawPath(path)

        self._paint_lane_label(painter, lane, accent)

        # Moc: kim cuong, moc dang chon co vong.
        for index, frame in enumerate(lane.frames):
            center = QPointF(lane.x_of(frame_time(frame)),
                             lane.y_of(frame_value(frame)))
            selected = (self._selected == (lane.prop, frame_time(frame))
                        or (self._drag and self._drag[0] == lane.prop
                            and self._drag[1] == index))
            self._paint_node(painter, center, accent, selected, frame)

    def _paint_lane_label(self, painter, lane, accent):
        """Ten property o giua le trai.

        De o DINH lane thi no trung hang voi nhan gia tri cua vach dau tien —
        hai chu bo vao nhau ngay tren cung mot duong.
        """
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(accent))
        painter.drawText(QRectF(8, lane.rect.top(), GUTTER_LEFT - 20,
                                lane.rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, lane_label(lane.prop))
        self._set_small_font(painter)

    def _set_small_font(self, painter):
        font = QFont(self.font())
        font.setPointSizeF(8.4)
        painter.setFont(font)

    def _paint_node(self, painter, center, accent, selected, frame):
        r = NODE_RADIUS
        diamond = QPainterPath()
        diamond.moveTo(center.x(), center.y() - r)
        diamond.lineTo(center.x() + r, center.y())
        diamond.lineTo(center.x(), center.y() + r)
        diamond.lineTo(center.x() - r, center.y())
        diamond.closeSubpath()
        # Tay cong ve tai dau moc = dao ham that cua duong cong doan di ra.
        slope = handle_slope(frame_ease(frame))
        if abs(slope) > 1e-6:
            painter.setPen(QPen(accent, 1.0))
            painter.drawLine(
                QPointF(center.x() - HANDLE_LENGTH,
                        center.y() + HANDLE_LENGTH * slope),
                QPointF(center.x() + HANDLE_LENGTH,
                        center.y() - HANDLE_LENGTH * slope))
        if selected:
            painter.setPen(QPen(accent, 1.6))
            painter.setBrush(QBrush(NODE_FILL))
            painter.drawPath(diamond)
            painter.setPen(QPen(accent, 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, r + 4, r + 4)
        else:
            painter.setPen(QPen(accent, 1.0))
            painter.setBrush(QBrush(NODE_FILL))
            painter.drawPath(diamond)
            painter.setBrush(Qt.NoBrush)

    def _paint_axis(self, painter, lane):
        """ truc thoi gian o DAY cung, duoi lane cuoi — ke vao giua hai lane
        thi no de len nhan gia tri cua lane duoi."""
        rect = lane.rect
        self._set_small_font(painter)
        left = lane.rect.left()
        right = lane.rect.right()
        for tick in tick_times(lane.t1):
            x = lane.x_of(tick)
            painter.setPen(QPen(LANE_EDGE))
            painter.drawLine(QPointF(x, rect.bottom()),
                             QPointF(x, rect.bottom() + 4))
            painter.setPen(QPen(AXIS_TEXT))
            # Nhan dau/cuoi can le trong vung ve, neu khong "0.00s" de len cot
            # so va "2.00s" bi cat mat ben phai.
            if x - left < 24:
                flags, box = Qt.AlignLeft, QRectF(x - 2, rect.bottom() + 5, 60,
                                                  AXIS_HEIGHT)
            elif right - x < 24:
                flags, box = Qt.AlignRight, QRectF(x - 58, rect.bottom() + 5,
                                                   60, AXIS_HEIGHT)
            else:
                flags, box = Qt.AlignHCenter, QRectF(x - 30, rect.bottom() + 5,
                                                     60, AXIS_HEIGHT)
            painter.drawText(box, flags | Qt.AlignTop, "%.2fs" % tick)

    def _paint_playhead(self, painter, lanes, clip):
        local = float(self._model.playhead) - float(clip.start_time)
        if local < 0.0 or local > lanes[0].t1:
            return
        top = lanes[0].rect.top()
        bottom = lanes[-1].rect.bottom()
        x = lanes[0].x_of(local)
        painter.setPen(QPen(PLAYHEAD, 1, Qt.DashLine))
        painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        painter.setBrush(QBrush(PLAYHEAD))
        painter.setPen(Qt.NoPen)
        head = QPainterPath()
        head.moveTo(x - 4, top - 6)
        head.lineTo(x + 4, top - 6)
        head.lineTo(x, top + 1)
        head.closeSubpath()
        painter.drawPath(head)
        painter.setBrush(Qt.NoBrush)

    # ── Tương tác ──────────────────────────────────────────────

    def lane_for(self, prop, clip=None):
        for lane in self._lanes(clip if clip is not None else self.clip()):
            if lane.prop == prop:
                return lane
        return None

    def _hit(self, point):
        """(dải chứa điểm, node dưới điểm).

        Hai điều phải giữ cùng lúc:
          * Trả về CẢ dải khi chấm vào chỗ trống — nhấp đúp để thêm mốc cần
            biết nó rơi vào dải nào; trả (None, None) thì tính năng thêm mốc
            bằng chuột im lặng chết.
          * Dải phải được mở ra đúng bằng vùng bam: moc dau/cuoi nam NGAY BEN
            LE lane (tan = thoi diet clip), nen thu hep theo rect nguyen van
            la nửa viên kim cương nhìn thấy được nhưng không bấm nổi. Bờ dưới
            mở theo nửa khe giữa hai lane để hai dải không chồng nhau.
        """
        clip = self.clip()
        if clip is None:
            return None, None
        for lane in self._lanes(clip):
            if not lane.rect.adjusted(-HIT_RADIUS, -LANE_GAP / 2.0,
                                      HIT_RADIUS,
                                      LANE_GAP / 2.0).contains(point):
                continue
            found = graph.hit_test(lane.frames, float(point.x()),
                                   float(point.y()), lane.prop, 0.0, lane.t1,
                                   lane.lo, lane.hi, lane.rect.left(),
                                   lane.rect.right(), lane.rect.top(),
                                   lane.rect.bottom(), radius=HIT_RADIUS)
            return lane, found
        return None, None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        point = event.position()
        lane, found = self._hit(point)
        if lane is None or found is None:
            self._selected = None
            self.update()
            return super().mousePressEvent(event)
        index, frame = found
        self._selected = (lane.prop, frame_time(frame))
        self._drag = (lane.prop, index, tuple(frame), frame_time(frame),
                      frame_value(frame))
        self.update()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._drag is None:
            over_node = self._hit(point)[1] is not None
            if over_node != self._hover_node:
                self._hover_node = over_node
                self.setCursor(Qt.PointingHandCursor if over_node
                                else Qt.ArrowCursor)
            return super().mouseMoveEvent(event)
        lane = self.lane_for(self._drag[0])
        if lane is None:
            return
        prop, index, old_frame, _t, _v = self._drag
        self._drag = (prop, index, old_frame, lane.time_at(point.x()),
                      lane.value_at(point.y()))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._drag is None:
            return super().mouseReleaseEvent(event)
        prop, _index, old_frame, time, value = self._drag
        self._drag = None
        moved = (abs(time - frame_time(old_frame)) > 1e-4
                 or abs(value - frame_value(old_frame)) > 1e-6)
        if moved:
            # Lenh push duoc moi cap nhat model; khong push thi moc phai tra
            # ve vi tri cu theo model vi model chua he biet den ban keo.
            self._push(EditKeyframeCommand(self._model, self._clip_id, prop,
                                           frame_time(old_frame), time, value),
                       prop)
            self._selected = (prop, time)
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Nhich kep vao cho trong = them moc tai do. Bam vao moc san thi
        khong them: khong ai muon hai moc trung nhau."""
        lane, found = self._hit(event.position())
        if found is not None or lane is None:
            return super().mouseDoubleClickEvent(event)
        clip = self.clip()
        time = lane.time_at(event.position().x())
        value = lane.value_at(event.position().y())
        self._push(AddKeyframeCommand(self._model, clip.clip_id, lane.prop,
                                      time, value,
                                      ease_before(clip, lane.prop, time)),
                   lane.prop)
        self._selected = (lane.prop, time)
        self.update()

    def contextMenuEvent(self, event):
        lane, found = self._hit(event.position())
        if lane is None or found is None:
            return
        _index, frame = found
        build_curve_menu(self, lane.prop, frame,
                         lambda ease, f=frame, p=lane.prop:
                         self.choose_ease(p, f, ease)
                         ).exec(event.globalPosition().toPoint())

    def curve_menu(self, prop, frame):
        """Seam de probe di qua dung menu cua chuot phai (exec la modal)."""
        return build_curve_menu(self, prop, frame,
                                lambda ease, f=frame, p=prop:
                                self.choose_ease(p, f, ease))

    def choose_ease(self, prop, frame, ease):
        time_sec = frame_time(frame)
        if ease == REMOVE_TOKEN:
            self._selected = None
            self._push(RemoveKeyframeCommand(self._model, self._clip_id, prop,
                                             time_sec), prop)
        else:
            self._push(SetKeyframeEaseCommand(self._model, self._clip_id, prop,
                                              time_sec, ease), prop)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.remove_selected():
                return
        super().keyPressEvent(event)

    def remove_selected(self):
        """Xoa moc dang chon — nut footer va phim Delete cung di qua day."""
        if not self._selected:
            return False
        prop, time = self._selected
        self._selected = None
        self._push(RemoveKeyframeCommand(self._model, self._clip_id, prop,
                                         time), prop)
        self.update()
        return True

    def add_at_playhead(self):
        """Them moc cho moi dang hien tai o dung playhead — cai ma nut kim
        cuong lam cho TUNG property, lam o day mot lan cho ca do thi."""
        clip = self.clip()
        if clip is None:
            return False
        local = float(self._model.playhead) - float(clip.start_time)
        if local < 0.0 or local > clip.duration:
            return False
        lanes = self._lanes(clip)
        added = 0
        for lane in lanes:
            existing = graph.frame_at(lane.frames, local, 0.05)
            on_curve = curve_at(clip, lane, local)
            if existing:
                # Moc da co o day: ghi lai dung diem duong cong dang cho, vi
                # playhead co the lech moc do vai phan tram giay.
                if abs(frame_value(existing) - on_curve) > 1e-6:
                    self._push(EditKeyframeCommand(
                        self._model, clip.clip_id, lane.prop,
                        frame_time(existing), local, on_curve), lane.prop)
                    added += 1
                continue
            self._push(AddKeyframeCommand(self._model, clip.clip_id, lane.prop,
                                          local, on_curve,
                                          ease_before(clip, lane.prop, local)),
                       lane.prop)
            added += 1
        self.update()
        return added > 0

    # ── Lệnh ───────────────────────────────────────────────────

    def _push(self, command, prop):
        self._undo.push(command)
        self.edited.emit(prop)


def build_curve_menu(parent, prop, frame, on_choose):
    """Menu 9 duong cong cho MOT moc — tach khoi exec de probe di qua duong that.

    QMenu.exec la modal nen probe khong mo duoc cua sổ; phan CHUA chon/da chon
    van duoc kiem tra truc tiep roi trigger action that, chi buoc hien menu la
    bo qua — cung cach menu cua node tren timeline.
    """
    menu = QMenu(parent)
    header = menu.addAction("%s @ %.2fs" % (lane_label(prop),
                                            frame_time(frame)))
    header.setEnabled(False)
    group = QActionGroup(menu)
    group.setExclusive(True)
    current = frame_ease(frame)
    for name in EASINGS:
        action = menu.addAction(EASE_LABELS.get(name, name))
        action.setData(name)
        action.setCheckable(True)
        action.setChecked(name == current)
        group.addAction(action)
        action.triggered.connect(lambda checked=False, key=name: on_choose(key))
    menu.addSeparator()
    remove = menu.addAction(font_icon("fa6s.trash", "#EF4444"), "Xóa mốc này")
    remove.setData(REMOVE_TOKEN)
    remove.triggered.connect(lambda checked=False: on_choose(REMOVE_TOKEN))
    return menu


class GraphTitleBar(QFrame):
    """Frameless thi phai keo duoc thanh tieu de — hop thoai nay song song voi
    timeline, khong di duoc la no che mat bang hinh."""

    def __init__(self, parent_dialog):
        super().__init__(parent_dialog)
        self.setObjectName("GraphTitleBar")
        self.setFixedHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 10, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(font_icon("fa6s.bezier-curve", "#40E0D0")
                       .pixmap(QSize(16, 16)))
        self.lbl_title = QLabel("Đồ thị đường cong")
        self.lbl_title.setObjectName("GraphTitle")
        close = QPushButton()
        close.setObjectName("GraphClose")
        close.setIcon(font_icon("fa6s.xmark", "#C8CBD4"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(26, 26)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(parent_dialog.reject)
        layout.addWidget(icon)
        layout.addWidget(self.lbl_title)
        layout.addStretch(1)
        layout.addWidget(close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)


class KeyframeGraphDialog(QDialog):
    """Hộp thoại không chặn bảng hình — đang chỉnh chuyển động thì phải còn
    thấy preview chạy theo."""

    def __init__(self, main_window, clip_id: str, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.clip_id = clip_id
        model = main_window.timeline_panel.model
        self.undo_stack = main_window.timeline_panel.undo_stack
        self.setObjectName("KeyframeGraphDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle("Đồ thị đường cong")
        self.setMinimumSize(640, 420)
        self.resize(880, 520)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(self._style())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.title_bar = GraphTitleBar(self)
        root.addWidget(self.title_bar)

        self.view = KeyframeGraphView(model, clip_id, self.undo_stack)
        self.view.edited.connect(lambda _prop: self._sync())
        root.addWidget(self.view, 1)

        root.addWidget(self._footer())
        model.clipRemoved.connect(self._on_clip_removed)
        for signal in (model.clipResized, model.clipUpdated, model.clipMoved):
            signal.connect(self._on_model_changed)
        self._refresh_title()

    # ── Chrome ─────────────────────────────────────────────────

    def set_clip(self, clip_id: str):
        """Mo do thi cua clip khac trong cung hop thoai."""
        self.clip_id = clip_id
        self.view.set_clip(clip_id)
        self._refresh_title()

    @property
    def lbl_title(self):
        return self.title_bar.lbl_title

    def _footer(self):
        bar = QFrame()
        bar.setObjectName("GraphFooter")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 10)
        layout.setSpacing(8)
        hint = QLabel("Kéo mốc để sửa · nhấp đúp để thêm · chuột phải đổi"
                      " đường cong · Delete để xóa")
        hint.setObjectName("GraphHint")
        self.btn_remove = QPushButton("Xóa mốc đang chọn")
        self.btn_remove.setObjectName("GraphSecondary")
        self.btn_remove.setIcon(font_icon("fa6s.trash", "#EF4444"))
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.clicked.connect(self.view.remove_selected)
        self.btn_undo = QPushButton("Hoàn tác")
        self.btn_undo.setObjectName("GraphSecondary")
        self.btn_undo.setIcon(font_icon("fa6s.rotate-left", "#D8DCE0"))
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.clicked.connect(self._undo_one)
        self.btn_add = QPushButton("Thêm mốc tại playhead")
        self.btn_add.setObjectName("GraphSecondary")
        self.btn_add.setIcon(font_icon("fa6s.plus", "#D8DCE0"))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.view.add_at_playhead)
        layout.addWidget(hint)
        layout.addStretch(1)
        layout.addWidget(self.btn_remove)
        layout.addWidget(self.btn_undo)
        layout.addWidget(self.btn_add)
        return bar

    @staticmethod
    def _style():
        return """
        QDialog { background-color: #14151A; border: 1px solid #34383D;
                  border-radius: 12px; color: #D8DCE0; }
        #GraphTitleBar { background-color: #1A1B26;
                  border-bottom: 1px solid #2A2D3A;
                  border-top-left-radius: 12px;
                  border-top-right-radius: 12px; }
        #GraphTitle { font-size: 15px; font-weight: 700; color: #FFFFFF;
                  background: transparent; border: none; }
        QLabel { background: transparent; border: none; }
        #GraphHint { color: #767C89; font-size: 11px; }
        #GraphClose { background: transparent; border: none; border-radius: 4px; }
        #GraphClose:hover { background: #FF4D4D; }
        #GraphFooter { background-color: #16171F;
                  border-top: 1px solid #2A2D3A;
                  border-bottom-left-radius: 12px;
                  border-bottom-right-radius: 12px; }
        QPushButton#GraphSecondary { background-color: #252729;
                  color: #D8DCE0; border: 1px solid #3A3A3A;
                  border-radius: 6px; padding: 6px 12px; font-size: 12px; }
        QPushButton#GraphSecondary:hover { border-color: #40E0D0; }
        """

    # ── Đồng bộ ────────────────────────────────────────────────

    def _refresh_title(self):
        clip = self.view.clip()
        if clip is None:
            self.lbl_title.setText("Đồ thị đường cong — (đã xóa)")
            return
        count = sum(len(graph.frames_of(clip, prop))
                    for prop in graph.animated_properties(clip))
        self.lbl_title.setText("Đồ thị đường cong — %s · %d mốc"
                               % (clip.name, count))

    def _sync(self):
        """Vẽ lại chính mình rồi bắt timeline và bảng thuộc tính đọc lại model.

        Timeline chỉ tái định vị node theo thời gian NÓ đang giữ, nên mốc đổi
        thời gian ở đây phải dựng lại node — cùng cách bảng thuộc tính vẫn làm.
        """
        self._refresh_title()
        clip = self.view.clip()
        if clip is None:
            return
        panel = self.main_window.timeline_panel
        item = panel.scene._clip_items.get(clip.clip_id)
        if item is not None:
            item.sync_keyframe_nodes_from_model()
        panel.scene.update()
        self.main_window.properties_panel.update_editor_values(clip)

    def _undo_one(self):
        if not self.undo_stack.can_undo:
            return False
        self.undo_stack.undo()
        self._sync()
        self.view.update()
        return True

    def _on_clip_removed(self, clip_id):
        if clip_id == self.clip_id:
            self._refresh_title()
            self.view.update()

    def _on_model_changed(self, *_args):
        self._refresh_title()
