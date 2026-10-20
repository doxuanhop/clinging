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

remove_dir("dist")
remove_dir("build")
remove_dir("temp_deps")
if os.path.exists("Clinging.spec"):
    os.remove("Clinging.spec")

print("Installing dependencies...")
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
    '--exclude-module=numpy._core.tests',
    '--exclude-module=numpy._typing.tests',
    '--exclude-module=numpy.lib.tests',
    '--exclude-module=numpy.linalg.tests',
    '--exclude-module=numpy.ma.tests',
    '--exclude-module=numpy.matrixlib.tests',
    '--exclude-module=numpy.polynomial.tests',
    '--exclude-module=numpy.random.tests',
    '--exclude-module=numpy.fft.tests',
    '--exclude-module=numpy.testing.tests',
    '--exclude-module=numpy.tests',
    '--exclude-module=numpy.f2py.tests',
    '--exclude-module=numpy._core._multiarray_tests',
    '--exclude-module=numpy._core._operand_flag_tests',
    '--exclude-module=numpy._core._rational_tests',
    '--exclude-module=numpy._core._struct_ufunc_tests',
    '--exclude-module=numpy._core._umath_tests',
    '--exclude-module=numpy._core.cversions',
    '--exclude-module=numpy._core.defchararray',
    '--exclude-module=numpy._core.einsumfunc',
    '--exclude-module=numpy._core.fromnumeric',
    '--exclude-module=numpy._core.function_base',
    '--exclude-module=numpy._core.getlimits',
    '--exclude-module=numpy._core.multiarray',
    '--exclude-module=numpy._core.numeric',
    '--exclude-module=numpy._core.records',
    '--exclude-module=numpy._core.shape_base',
    '--exclude-module=numpy._core.ufunc',
    '--exclude-module=numpy._core.umath',
    '--distpath=dist',
    '--workpath=build',
    '--specpath=.',
    '--noconfirm',
])

shutil.rmtree("temp_deps", ignore_errors=True)
print("\nBuild completed!")
print("Executable: dist/Clinging.exe")