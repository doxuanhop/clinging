@echo off
chcp 65001 >nul
title Clinging - Build Installer

echo ========================================
echo   Clinging Video Editor - Build .EXE
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

echo [1/6] Installing PyInstaller...
python -m pip install pyinstaller --user
if errorlevel 1 (
    echo [WARNING] PyInstaller install failed, trying alternate method...
    python -m pip install --ignore-installed pyinstaller --user
)

echo [2/6] Installing dependencies...
python -m pip install moviepy --user
python -m pip install numpy --user
python -m pip install mss --user
python -m pip install opencv-python --user
python -m pip install Pillow --user
python -m pip install customtkinter --user
python -m pip install faster-whisper --user
python -m pip install gtts --user
python -m pip install requests --user

REM Try playsound, skip if fails
python -m pip install playsound --user 2>nul
if errorlevel 1 (
    echo [WARNING] playsound skipped (compatibility issue)
)

REM Clean previous builds
echo [3/6] Cleaning previous builds...
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"
if exist "Clinging.spec" del "Clinging.spec" 2>nul

REM Build with PyInstaller
echo [4/6] Building .EXE...
echo.

python -m PyInstaller main.py ^
    --name "Clinging" ^
    --onefile ^
    --windowed ^
    --add-data "data;data" ^
    --add-data "src;src" ^
    --hidden-import=tkinter ^
    --hidden-import=tkinter.ttk ^
    --hidden-import=tkinter.filedialog ^
    --hidden-import=tkinter.messagebox ^
    --hidden-import=customtkinter ^
    --hidden-import=customtkinter.windows ^
    --hidden-import=customtkinter.windows.widgets ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageTk ^
    --hidden-import=numpy ^
    --hidden-import=cv2 ^
    --hidden-import=moviepy ^
    --hidden-import=moviepy.editor ^
    --hidden-import=moviepy.video.io ^
    --hidden-import=threading ^
    --hidden-import=faster_whisper ^
    --hidden-import=gtts ^
    --hidden-import=requests ^
    --hidden-import=src.asr ^
    --hidden-import=os ^
    --hidden-import=sys ^
    --hidden-import=subprocess ^
    --hidden-import=tempfile ^
    --hidden-import=shutil ^
    --hidden-import=json ^
    --hidden-import=time ^
    --hidden-import=datetime ^
    --hidden-import=traceback ^
    --hidden-import=zipfile ^
    --collect-all customtkinter ^
    --collect-all moviepy ^
    --collect-all faster_whisper ^
    --noconfirm ^
    --clean

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    echo.
    echo Try running manually:
    echo python -m PyInstaller main.py --onefile --windowed
    pause
    exit /b 1
)

echo.
echo [5/6] Copying additional files...
echo.

REM Copy data folder if exists
if exist "data" (
    if not exist "dist\data" mkdir "dist\data"
    xcopy /e /y "data\*" "dist\data\" >nul 2>&1
)

if exist "src" (
    if not exist "dist\src" mkdir "dist\src"
    xcopy /e /y "src\*" "dist\src\" >nul 2>&1
)

REM Auto Captions uses this ffmpeg when the PC has none installed
if exist "AsrTools-v1.1.0\ffmpeg.exe" (
    if not exist "dist\AsrTools-v1.1.0" mkdir "dist\AsrTools-v1.1.0"
    copy /y "AsrTools-v1.1.0\ffmpeg.exe" "dist\AsrTools-v1.1.0\" >nul 2>&1
)

echo [6/6] Build complete!
echo.
echo ========================================
echo   Output: dist\Clinging.exe
echo ========================================
echo.
echo Done!
pause