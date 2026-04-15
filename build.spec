# -*- mode: python ; coding: utf-8 -*-
#
# SecureDelete — PyInstaller build spec
# Run with:  pyinstaller build.spec
#

from PyInstaller.utils.hooks import collect_all

# Collect everything customtkinter ships (themes, images, fonts)
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all('customtkinter')

a = Analysis(
    ['securedelete_gui.py'],
    pathex=['.'],
    binaries=ctk_binaries,
    datas=ctk_datas,
    hiddenimports=ctk_hiddenimports + [
        'securedelete',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'ctypes',
        'threading',
        'subprocess',
        'json',
        'base64',
        'glob',
        'shutil',
        'secrets',
        'stat',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SecureDelete',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No black console window — pure GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,         # Always request elevation — required for shredding, raw disk access
    icon='icon.ico',        # Shield app icon
    version='version_info.txt',
)
