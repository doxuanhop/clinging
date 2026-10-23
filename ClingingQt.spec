# -*- mode: python ; coding: utf-8 -*-
# Bản dựng app Qt (Clinging). Chạy: pyinstaller ClingingQt.spec
# FFmpeg/ffprobe ĐƯỢC đóng gói: tools/ffmpeg/*.exe -> _internal/tools/, để bản
# cài chạy trên một máy sạch không có gì trong PATH (xem core/external_tools.py).

# styles/*.qss, assets/app-icon và assets/icons (font glyph + charmap) được nạp
# lúc chạy nên phải là data.
# src/ là namespace package (không có __init__.py ở gốc). Chỉ src/asr là mã
# chạy thật: src/logic.py và src/background_tasks.py là xác CustomTkinter cũ
# (nhập tkinter — thứ bị exclude ở dưới), src/anim.py đã được port vào core/.
# Copy nguyên src/ nghĩa là đóng gói ba file mà bản cài không bao giờ import
# được, nên --import-report chỉ quét những gì thực sự chạy.
datas = [('styles', 'styles'), ('assets', 'assets'), ('src/asr', 'src/asr')]

# Hai file thực thi này là ~205 MB nhưng là lý do bản cài chạy được offline.
binaries = [('tools/ffmpeg/ffmpeg.exe', 'tools'),
            ('tools/ffmpeg/ffprobe.exe', 'tools')]

hiddenimports = ['theme', 'diagnostics', 'bar_measure', 'psutil',
                 'core.external_tools',
                 'core.thumbnail_export', 'ui.thumbnail_dialog',
                 'core.media_splitter', 'ui.split_dialog',
                 'core.keyframe_graph', 'ui.keyframe_graph_dialog',
                 'core.media_compress', 'ui.compress_dialog',
                 'core.export_range', 'ui.export_dialog',
                 'core.sfx', 'ui.sfx_dialog',
                 'core.canvas_layout', 'ui.canvas_layout_dialog',
                 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
                 'PySide6.QtMultimedia', 'PySide6.QtSvg']

# qtawesome bị bỏ khỏi bundle: nó kéo theo qtpy + PySide6.QtOpenGL/
# QtDataVisualization mà không ai dùng, đo 0,6 s lúc khởi động và ~29 MB private
# (scratch/boot_low_spec_probe.py). widgets/fontawesome.py vẽ cùng glyph từ
# assets/icons/*.ttf — thư mục đó đã nằm trong datas ở trên. 'qtawesome' bị
# exclude để nó không len lại được theo một lệnh import mới; dòng "font icon"
# của --selftest là thứ bắt nếu ai đó gọi lại nó.
#
# 'faster_whisper' từng được import TRONG LÒNG một hàm ở core/auto_captions.py.
# PyInstaller đọc bytecode của cả hàm, nên một câu import mà không đường nào
# chạy offline kéo theo ~193 MB: ctranslate2 61.6 + av.libs 65.6 + onnxruntime
# 39.3 + tokenizers 7.9 + hf_xet 9.4 + pydantic_core 5.3. Engine đó đã bị loại
# khỏi ENGINES; exclude ở đây là hàng rào để nó không quay lại theo đường import
# mới, và --selftest là thứ chứng minh phần còn vẫn đủ.
_excludes = ['tkinter', 'customtkinter', 'moviepy', 'faster_whisper', 'qtawesome',
             'ctranslate2', 'onnxruntime', 'av', 'av.playback', 'av.video',
             'huggingface_hub', 'hf_xet', 'tokenizers', 'pydantic',
             'pydantic_core', 'aiohttp', 'multidict', 'frozenlist', 'propcache',
             'yarl', 'tqdm', 'datasets', 'torch']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Clinging',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='packaging/version_info.txt',
    icon='assets/app-icon/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Clinging',
)
