# -*- mode: python ; coding: utf-8 -*-
import glob
from PyInstaller.utils.hooks import collect_all

datas = [
    ('assets', 'assets'),
    ('pokemons.txt', '.'),
    ('anubicide_logo.ico', '.'),
]
for f in glob.glob('*.png'):
    datas.append((f, '.'))

binaries = []
hiddenimports = [
    'customtkinter',
    'PIL',
    'cv2',
    'pyautogui',
    'pygetwindow',
    'keyboard',
    'pytesseract',
    'numpy',
    'discord_notifier',
    'timeout_manager',
    'bot_core',
    'bot_gui',
]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

excludes = [
    'torch',
    'torchvision',
    'scipy',
    'pandas',
    'matplotlib',
    'IPython',
    'jupyter',
    'sqlalchemy',
    'pyarrow',
    'pytest',
    'sympy',
    'notebook',
    'sklearn',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='anubicide_cracked',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='anubicide_logo.ico',
)
