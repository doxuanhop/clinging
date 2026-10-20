import PyInstaller.__main__
import os
import shutil
import time
import sys

def remove_dir(path):
    if os.path.exists(path):
        for retry in range(3):
            try:
                shutil.rmtree(path)
                break
            except PermissionError:
                if retry < 2:
                    time.sleep(1)
                else:
                    print(f"Warning: Could not remove {path}")

remove_dir("dist")
remove_dir("build")
remove_dir("temp_deps")
if os.path.exists("Clinging.spec"):
    os.remove("Clinging.spec")

print("Installing dependencies to temp folder...")
os.system(f"{sys.executable} -m pip install moviepy numpy pillow -q -t temp_deps")

PyInstaller.__main__.run([
    'main.py',
    '--name=Clinging',
    '--onefile',
    '--windowed',
    '--icon=icons\\48x48.ico',
    '--add-data=temp_deps;.',
    '--hidden-import=tkinter',
    '--hidden-import=tkinter.filedialog',
    '--hidden-import=tkinter.messagebox',
    '--hidden-import=tkinter.ttk',
    '--hidden-import=threading',
    '--hidden-import=datetime',
    '--hidden-import=os',
    '--hidden-import=numpy',
    '--hidden-import=decorator',
    '--hidden-import=functools',
    '--collect-all=numpy',
    '--distpath=dist',
    '--workpath=build',
    '--specpath=.',
    '--clean',
    '--noconfirm',
])

shutil.rmtree("temp_deps", ignore_errors=True)

print("\nBuild completed!")
print("Executable: dist/Clinging.exe")