# -*- mode: python ; coding: utf-8 -*-
# Bản dựng app Qt (Clinging). Chạy: pyinstaller ClingingQt.spec
# FFmpeg/ffprobe ĐƯỢC đóng gói: tools/ffmpeg/*.exe -> _internal/tools/, để bản
# cài chạy trên một máy sạch không có gì trong PATH (xem core/external_tools.py).
from PyInstaller.utils.hooks import collect_all

# styles/*.qss và assets/app-icon được nạp lúc chạy nên phải là data.
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
                 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
                 'PySide6.QtMultimedia', 'PySide6.QtSvg']

for _pkg in ('qtawesome',):
    _ret = collect_all(_pkg)
    datas += _ret[0]
    binaries += _ret[1]
    hiddenimports += _ret[2]

# 'faster_whisper' từng được import TRONG LÒNG một hàm ở core/auto_captions.py.
# PyInstaller đọc bytecode của cả hàm, nên một câu import mà không đường nào
# chạy offline kéo theo ~193 MB: ctranslate2 61.6 + av.libs 65.6 + onnxruntime
# 39.3 + tokenizers 7.9 + hf_xet 9.4 + pydantic_core 5.3. Engine đó đã bị loại
# khỏi ENGINES; exclude ở đây là hàng rào để nó không quay lại theo đường import
# mới, và --selftest là thứ chứng minh phần còn vẫn đủ.
_excludes = ['tkinter', 'customtkinter', 'moviepy', 'faster_whisper',
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
