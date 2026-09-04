# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


root = Path(SPECPATH)
python_root = Path(sys.base_prefix)
tcl_root = python_root / "tcl"
tkinter_root = python_root / "Lib" / "tkinter"
dll_root = python_root / "DLLs"

# Some portable/uv Python distributions can import Tkinter normally, while
# PyInstaller's Tk probe still marks the installation as broken. Collect the
# package, extension module, DLLs, and Tcl/Tk scripts explicitly so the frozen
# application does not depend on that probe succeeding.
tk_data = []
for directory, target in (("tcl8.6", "_tcl_data"), ("tk8.6", "_tk_data")):
    source = tcl_root / directory
    if source.exists():
        tk_data.append((str(source), target))

if tkinter_root.exists():
    tk_data.append((str(tkinter_root), "tkinter"))

tk_binaries = []
for filename in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
    source = dll_root / filename
    if source.exists():
        tk_binaries.append((str(source), "."))

a = Analysis(
    ["id_photo_bg_changer.py"],
    pathex=[str(root)],
    binaries=tk_binaries,
    datas=[
        (str(root / "pictone" / "models" / "modnet_photographic.onnx"), "pictone/models"),
        (str(root / "pictone" / "models" / "face_detection_yunet_2023mar.onnx"), "pictone/models"),
        (str(root / "pictone" / "assets" / "app_icon.ico"), "assets"),
        (str(root / "pictone" / "assets" / "app_background.png"), "assets"),
        (str(root / "THIRD_PARTY_NOTICES.md"), "."),
    ] + tk_data,
    hiddenimports=[
        "_tkinter",
        "tkinter",
        "tkinter.colorchooser",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.ttk",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt6", "matplotlib", "scipy", "http.server", "webbrowser"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="证件照换底色",
    icon=str(root / "pictone" / "assets" / "app_icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
